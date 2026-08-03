"""Read-only Session facts projected for Memory Maintenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.maintenance import BusinessDay

from .errors import SessionContractError, SessionInvariantError
from .models import SessionSummaryRecord, SessionTurnRecord
from .store import SessionStore
from .validation import validate_summary_record, validate_turn_record


@dataclass(frozen=True)
class SessionMemoryFact:
    """One committed Turn projected without trace or execution metadata."""

    ref: str
    started_at: datetime
    user_inputs: tuple[str, ...]
    working: JsonObject = field(default_factory=dict)
    background_links: tuple[str, ...] = field(default_factory=tuple)
    answer: str = ""
    references: tuple[str, ...] = field(default_factory=tuple)
    actions: tuple[JsonObject, ...] = field(default_factory=tuple)
    exhausted: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.ref, str) or not self.ref.startswith("session:turn/"):
            raise SessionContractError("Session memory fact requires a Turn ref")
        if not isinstance(self.started_at, datetime) or self.started_at.tzinfo is None:
            raise SessionContractError(
                "Session memory fact started_at must be timezone-aware"
            )
        for name in ("user_inputs", "background_links", "references"):
            values = tuple(getattr(self, name))
            if any(not isinstance(item, str) or not item for item in values):
                raise SessionContractError(
                    f"Session memory fact {name} must contain non-empty strings"
                )
            object.__setattr__(self, name, values)
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
        }


@dataclass(frozen=True)
class SessionMemoryFactsProjection:
    day: BusinessDay
    revision: int
    facts: tuple[SessionMemoryFact, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.day, BusinessDay):
            raise SessionContractError(
                "Session memory projection day must be a BusinessDay"
            )
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise SessionContractError(
                "Session memory projection revision must be non-negative"
            )
        facts = tuple(self.facts)
        if any(not isinstance(fact, SessionMemoryFact) for fact in facts):
            raise SessionContractError("Session memory projection facts are invalid")
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
    refs: tuple[str, ...],
) -> SessionMemoryFactsProjection:
    """Expand one validated Session graph to chronological Turn facts."""

    store = SessionStore(root=root)
    visited: set[str] = set()
    facts: list[SessionMemoryFact] = []

    def visit(ref: str) -> None:
        if ref in visited:
            raise SessionInvariantError(
                f"Session memory graph contains duplicate ref: {ref}"
            )
        visited.add(ref)
        record = store.load_record(ref)
        if isinstance(record, SessionSummaryRecord):
            summary = validate_summary_record(record)
            for child_ref in summary.child_refs:
                visit(child_ref)
            return
        facts.append(_turn_fact(validate_turn_record(record)))

    for ref in refs:
        visit(ref)
    facts.sort(key=lambda fact: (fact.started_at, fact.ref))
    return SessionMemoryFactsProjection(
        day=day,
        revision=revision,
        facts=tuple(facts),
    )


def _turn_fact(record: SessionTurnRecord) -> SessionMemoryFact:
    output = record.output
    return SessionMemoryFact(
        ref=record.ref,
        started_at=_turn_started_at(record),
        user_inputs=tuple(item.text for item in record.inputs),
        working=record.working,
        background_links=record.background_links,
        answer=output.text if output is not None else "",
        references=output.references if output is not None else (),
        actions=tuple(action.to_json() for action in record.actions),
        exhausted=record.exhausted,
    )


def _turn_started_at(record: SessionTurnRecord) -> datetime:
    for item in record.inputs:
        try:
            return datetime.fromtimestamp(float(item.received_at), tz=UTC)
        except (OverflowError, OSError, ValueError):
            continue
    return datetime.fromtimestamp(record.recorded_at_ns / 1_000_000_000, tz=UTC)
