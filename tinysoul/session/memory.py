"""Read-only Session facts projected for Memory Maintenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.loop.day import BusinessDay

from .errors import SessionContractError, SessionInvariantError
from .models import SessionHistoryItem, SessionHistoryKind, SessionRecord
from .store import SessionStore


@dataclass(frozen=True)
class SessionMemoryFact:
    """One committed Turn projected without raw trace or provider detail."""

    ref: str
    started_at: datetime
    user_inputs: tuple[str, ...]
    working: JsonObject = field(default_factory=dict)
    background_links: tuple[str, ...] = field(default_factory=tuple)
    answer: str = ""
    references: tuple[str, ...] = field(default_factory=tuple)
    actions: tuple[JsonObject, ...] = field(default_factory=tuple)
    exhausted: bool = False
    trace_digest: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.ref, str) or not self.ref.startswith("session:turn/"):
            raise SessionContractError("Session memory fact requires a Turn ref")
        if not isinstance(self.started_at, datetime) or self.started_at.tzinfo is None:
            raise SessionContractError(
                "Session memory fact started_at must be timezone-aware"
            )
        for name, values in (
            ("user_inputs", self.user_inputs),
            ("background_links", self.background_links),
            ("references", self.references),
        ):
            items = tuple(values)
            if any(not isinstance(item, str) or not item for item in items):
                raise SessionContractError(
                    f"Session memory fact {name} must contain non-empty strings"
                )
            object.__setattr__(self, name, items)
        if not isinstance(self.answer, str) or not isinstance(self.exhausted, bool):
            raise SessionContractError("Session memory fact output is invalid")
        actions = tuple(self.actions)
        if any(not isinstance(action, dict) for action in actions):
            raise SessionContractError(
                "Session memory fact actions must contain JSON objects"
            )
        object.__setattr__(
            self,
            "actions",
            tuple(to_json_object(action) for action in actions),
        )
        object.__setattr__(self, "working", to_json_object(self.working))
        object.__setattr__(self, "trace_digest", to_json_object(self.trace_digest))

    def to_json(self) -> JsonObject:
        return {
            "ref": self.ref,
            "started_at": self.started_at.isoformat(),
            "user_inputs": list(self.user_inputs),
            "working": self.working,
            "background_links": list(self.background_links),
            "answer": self.answer,
            "references": list(self.references),
            "actions": list(self.actions),
            "exhausted": self.exhausted,
            "trace_digest": self.trace_digest,
        }


@dataclass(frozen=True)
class SessionMemoryFactsProjection:
    """Complete reachable Turn facts for one validated Session archive."""

    day: BusinessDay
    revision: int
    facts: tuple[SessionMemoryFact, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.day, BusinessDay):
            raise SessionContractError(
                "Session memory projection day must be a BusinessDay"
            )
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise SessionContractError(
                "Session memory projection revision must be non-negative"
            )
        facts = tuple(self.facts)
        if any(not isinstance(fact, SessionMemoryFact) for fact in facts):
            raise SessionContractError(
                "Session memory projection facts are invalid"
            )
        if len({fact.ref for fact in facts}) != len(facts):
            raise SessionContractError(
                "Session memory projection facts must have unique refs"
            )
        object.__setattr__(self, "facts", facts)

    @property
    def has_facts(self) -> bool:
        return bool(self.facts)


def project_session_memory_facts(
    *,
    day: BusinessDay,
    root: Path,
    revision: int,
    items: tuple[SessionHistoryItem, ...],
) -> SessionMemoryFactsProjection:
    """Expand the committed Summary graph to unique chronological Turn facts."""

    store = SessionStore(root=root)
    visited: set[str] = set()
    facts: list[SessionMemoryFact] = []

    def visit(item: SessionHistoryItem) -> None:
        if item.ref in visited:
            return
        visited.add(item.ref)
        record = store.load_record(item.ref)
        if record.kind is not item.kind:
            raise SessionInvariantError(
                f"Session memory projection kind mismatch: {item.ref}"
            )
        if record.kind is SessionHistoryKind.SUMMARY:
            for child in _summary_children(record):
                visit(child)
            return
        facts.append(_turn_fact(record))

    for item in items:
        visit(item)
    facts.sort(key=lambda fact: (fact.started_at, fact.ref))
    return SessionMemoryFactsProjection(
        day=day,
        revision=revision,
        facts=tuple(facts),
    )


def _summary_children(record: SessionRecord) -> tuple[SessionHistoryItem, ...]:
    raw_children = record.content.get("children")
    if not isinstance(raw_children, list) or len(raw_children) < 2:
        raise SessionInvariantError(
            f"Session summary record has invalid children: {record.ref}"
        )
    children: list[SessionHistoryItem] = []
    for raw in raw_children:
        if not isinstance(raw, dict):
            raise SessionInvariantError(
                f"Session summary record has a non-object child: {record.ref}"
            )
        children.append(SessionHistoryItem.from_json(to_json_object(raw)))
    raw_refs = record.content.get("child_refs")
    if raw_refs != [child.ref for child in children]:
        raise SessionInvariantError(
            f"Session summary record child refs are inconsistent: {record.ref}"
        )
    return tuple(children)


def _turn_fact(record: SessionRecord) -> SessionMemoryFact:
    if record.kind is not SessionHistoryKind.TURN:
        raise SessionInvariantError(
            f"Session memory fact source is not a Turn: {record.ref}"
        )
    completion = _object(record.content, "completion", ref=record.ref)
    background = _object(record.content, "background", ref=record.ref)
    inputs = _objects(completion.get("inputs"), label="inputs", ref=record.ref)
    user_inputs = tuple(
        text
        for item in inputs
        if isinstance((text := item.get("text")), str) and text
    )
    started_at = _turn_started_at(inputs, record=record)
    output = record.content.get("output")
    if output is not None and not isinstance(output, dict):
        raise SessionInvariantError(
            f"Session Turn output is not an object: {record.ref}"
        )
    output_value = to_json_object(output) if isinstance(output, dict) else {}
    actions = _objects(background.get("actions", []), label="actions", ref=record.ref)
    exhausted = record.content.get("exhausted", False)
    if not isinstance(exhausted, bool):
        raise SessionInvariantError(
            f"Session Turn exhausted flag is invalid: {record.ref}"
        )
    return SessionMemoryFact(
        ref=record.ref,
        started_at=started_at,
        user_inputs=user_inputs,
        working=_optional_object(completion.get("working"), ref=record.ref),
        background_links=_strings(
            completion.get("background_links", []),
            label="background_links",
            ref=record.ref,
        ),
        answer=_optional_text(output_value.get("text")),
        references=_strings(
            output_value.get("references", []),
            label="references",
            ref=record.ref,
        ),
        actions=tuple(actions),
        exhausted=exhausted,
        trace_digest=_optional_object(
            completion.get("trace_digest"),
            ref=record.ref,
        ),
    )


def _turn_started_at(
    inputs: tuple[JsonObject, ...],
    *,
    record: SessionRecord,
) -> datetime:
    for item in inputs:
        value = item.get("received_at")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            continue
    return datetime.fromtimestamp(record.recorded_at_ns / 1_000_000_000, tz=UTC)


def _object(value: JsonObject, name: str, *, ref: str) -> JsonObject:
    item = value.get(name)
    if not isinstance(item, dict):
        raise SessionInvariantError(
            f"Session Turn is missing {name}: {ref}"
        )
    return to_json_object(item)


def _optional_object(value: object, *, ref: str) -> JsonObject:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SessionInvariantError(
            f"Session Turn contains a non-object fact: {ref}"
        )
    return to_json_object(value)


def _objects(value: object, *, label: str, ref: str) -> tuple[JsonObject, ...]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SessionInvariantError(
            f"Session Turn {label} must contain objects: {ref}"
        )
    return tuple(to_json_object(item) for item in value if isinstance(item, dict))


def _strings(value: object, *, label: str, ref: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise SessionInvariantError(
            f"Session Turn {label} must contain non-empty strings: {ref}"
        )
    return tuple(item for item in value if isinstance(item, str))


def _optional_text(value: object) -> str:
    return value if isinstance(value, str) else ""
