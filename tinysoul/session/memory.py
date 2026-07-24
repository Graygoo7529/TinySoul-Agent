"""Read-only Session facts projected for Memory Maintenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from tinysoul.context import is_canonical_trace_digest
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.loop.day import BusinessDay

from .errors import SessionContractError, SessionInvariantError
from .models import SessionHistoryItem, SessionHistoryKind, SessionRecord
from .store import SessionStore
from .validation import validate_turn_record


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
    action_history: JsonObject = field(default_factory=dict)
    exhausted: bool = False
    trace_summary: JsonObject = field(default_factory=dict)
    trace_digest: str = ""

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
        object.__setattr__(
            self,
            "action_history",
            to_json_object(self.action_history),
        )
        object.__setattr__(self, "trace_summary", to_json_object(self.trace_summary))
        if not is_canonical_trace_digest(self.trace_digest):
            raise SessionContractError(
                "Session memory fact trace_digest must be a sha256 content digest"
            )

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
            "action_history": self.action_history,
            "exhausted": self.exhausted,
            "trace_summary": self.trace_summary,
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
    validated = validate_turn_record(record)
    inputs = validated.inputs
    user_inputs = tuple(
        text
        for item in inputs
        if isinstance((text := item.get("text")), str) and text
    )
    started_at = _turn_started_at(inputs, record=record)
    output_value = validated.output or {}
    return SessionMemoryFact(
        ref=record.ref,
        started_at=started_at,
        user_inputs=user_inputs,
        working=validated.working,
        background_links=validated.background_links,
        answer=_optional_text(output_value.get("text")),
        references=_strings(
            output_value.get("references", []),
            label="references",
            ref=record.ref,
        ),
        actions=validated.background_actions,
        action_history=validated.action_projection.summary_json(),
        exhausted=validated.exhausted,
        trace_summary=validated.trace_summary,
        trace_digest=validated.trace_digest,
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
