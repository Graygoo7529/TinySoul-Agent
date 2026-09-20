"""Typed requests, plans, availability, and outcomes for Reflection."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from tinysoul.infra.json import JsonObject, to_json_object

from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.kernel.loop.turn import TurnOutcome
from .errors import ReflectionContractError


class ReflectionScope(StrEnum):
    DAILY = "daily"
    HOME = "home"
    MEMORY = "memory"


class ReflectionTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class ReflectionTaskKind(StrEnum):
    ARCHIVE = "archive"
    HOME = "home"
    MEMORY = "memory"


class ReflectionTaskStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    AWAITING_USER = "awaiting_user"
    STOPPED = "stopped"
    EXHAUSTED = "exhausted"
    CANCELLED = "cancelled"


class ReflectionStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"
    AWAITING_USER = "awaiting_user"
    STOPPED = "stopped"
    EXHAUSTED = "exhausted"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ReflectionRequest:
    scope: ReflectionScope
    trigger: ReflectionTrigger
    target_day: CalendarDay | None = None
    source: str = ""
    instructions: str = ""
    request_id: str = field(default_factory=lambda: f"request_{uuid4().hex}")
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ReflectionScope):
            raise ReflectionContractError("Reflection request scope is invalid")
        if not isinstance(self.trigger, ReflectionTrigger):
            raise ReflectionContractError("Reflection request trigger is invalid")
        if self.target_day is not None and not isinstance(self.target_day, CalendarDay):
            raise ReflectionContractError("Reflection request target_day is invalid")
        if self.scope is not ReflectionScope.MEMORY and self.target_day is not None:
            raise ReflectionContractError(
                "Only Memory Reflection can target an explicit day"
            )
        if self.scope is ReflectionScope.MEMORY and self.target_day is None:
            raise ReflectionContractError(
                "Memory Reflection requires an explicit target day"
            )
        if not isinstance(self.source, str):
            raise ReflectionContractError("Reflection request source must be text")
        if not isinstance(self.instructions, str) or len(self.instructions) > 16000:
            raise ReflectionContractError(
                "Reflection instructions must be text of at most 16000 characters"
            )
        if (
            self.trigger is ReflectionTrigger.MANUAL
            and self.scope is ReflectionScope.DAILY
        ):
            raise ReflectionContractError(
                "Manual Reflection must select Home or one closed Memory day"
            )
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ReflectionContractError("Reflection request_id must be non-empty")
        object.__setattr__(self, "request_id", self.request_id.strip())
        object.__setattr__(self, "metadata", to_json_object(self.metadata))

    def to_json(self) -> JsonObject:
        value: JsonObject = {
            "scope": self.scope.value,
            "trigger": self.trigger.value,
            "source": self.source,
            "instructions": self.instructions,
            "request_id": self.request_id,
            "metadata": self.metadata,
        }
        if self.target_day is not None:
            value["target_day"] = str(self.target_day)
        return value


@dataclass(frozen=True)
class ReflectionTaskOutcome:
    kind: ReflectionTaskKind
    status: ReflectionTaskStatus
    target_day: CalendarDay | None = None
    reason: str = ""
    details: JsonObject = field(default_factory=dict)
    turn_outcome: TurnOutcome | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReflectionTaskKind):
            raise ReflectionContractError("Reflection task kind is invalid")
        if not isinstance(self.status, ReflectionTaskStatus):
            raise ReflectionContractError("Reflection task status is invalid")
        if self.target_day is not None and not isinstance(self.target_day, CalendarDay):
            raise ReflectionContractError("Reflection task target_day is invalid")
        if not isinstance(self.reason, str):
            raise ReflectionContractError("Reflection task reason must be text")
        if self.turn_outcome is not None and not isinstance(
            self.turn_outcome, TurnOutcome
        ):
            raise ReflectionContractError("Reflection task Turn outcome is invalid")
        object.__setattr__(self, "details", to_json_object(self.details))

    def to_json(self) -> JsonObject:
        value: JsonObject = {
            "kind": self.kind.value,
            "status": self.status.value,
            "details": self.details,
        }
        if self.target_day is not None:
            value["target_day"] = str(self.target_day)
        if self.reason:
            value["reason"] = self.reason
        if self.turn_outcome is not None:
            turn = self.turn_outcome
            value["turn"] = {
                "status": turn.status.value,
                "completion": turn.completion,
                "failure": turn.failure.to_json() if turn.failure is not None else None,
                "finish_failures": [
                    failure.to_json() for failure in turn.finish_failures
                ],
                "cleanup": [
                    {"resource": item.resource, "error_type": item.error_type}
                    for item in turn.cleanup_diagnostics
                ],
            }
        return value

    @classmethod
    def from_turn(
        cls,
        kind: ReflectionTaskKind,
        outcome: TurnOutcome,
        *,
        target_day: CalendarDay | None = None,
        details: JsonObject | None = None,
    ) -> ReflectionTaskOutcome:
        statuses = {
            TurnOutcomeStatus.COMPLETED: ReflectionTaskStatus.COMPLETED,
            TurnOutcomeStatus.AWAITING_USER: ReflectionTaskStatus.AWAITING_USER,
            TurnOutcomeStatus.STOPPED: ReflectionTaskStatus.STOPPED,
            TurnOutcomeStatus.EXHAUSTED: ReflectionTaskStatus.EXHAUSTED,
            TurnOutcomeStatus.FAILED: ReflectionTaskStatus.FAILED,
            TurnOutcomeStatus.CANCELLED: ReflectionTaskStatus.CANCELLED,
        }
        if outcome.status not in statuses:
            raise ReflectionContractError("Unexpected Reflection Turn outcome")
        return cls(
            kind=kind,
            status=statuses[outcome.status],
            target_day=target_day,
            details=details or {},
            turn_outcome=outcome,
        )


@dataclass(frozen=True)
class ReflectionOutcome:
    request_id: str
    active_day: CalendarDay
    status: ReflectionStatus
    tasks: tuple[ReflectionTaskOutcome, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ReflectionContractError("Reflection outcome request_id is invalid")
        if not isinstance(self.active_day, CalendarDay):
            raise ReflectionContractError("Reflection outcome active_day is invalid")
        if not isinstance(self.status, ReflectionStatus):
            raise ReflectionContractError("Reflection outcome status is invalid")
        if any(not isinstance(item, ReflectionTaskOutcome) for item in self.tasks):
            raise ReflectionContractError("Reflection outcome tasks are invalid")
        object.__setattr__(self, "tasks", tuple(self.tasks))

    def to_json(self) -> JsonObject:
        return {
            "request_id": self.request_id,
            "active_day": str(self.active_day),
            "status": self.status.value,
            "tasks": [task.to_json() for task in self.tasks],
        }


class ReflectionExecutionCancelled(asyncio.CancelledError):
    """Cancellation carrying the Reflection owner's completed facts."""

    def __init__(self, outcome: ReflectionOutcome) -> None:
        super().__init__("Reflection execution was interrupted")
        self.outcome = outcome


@dataclass(frozen=True)
class ReflectionAvailability:
    checked_day: CalendarDay
    home_change_count: int = 0
    home_skill_memory_count: int = 0
    memory_days: tuple[CalendarDay, ...] = field(default_factory=tuple)
    missing_daily_days: tuple[CalendarDay, ...] = field(default_factory=tuple)
    next_before: CalendarDay | None = None
    scanned_days: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.checked_day, CalendarDay):
            raise ReflectionContractError(
                "Reflection availability checked day is invalid"
            )
        for value in (self.home_change_count, self.home_skill_memory_count):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ReflectionContractError(
                    "Reflection availability counts must be non-negative integers"
                )
        if any(not isinstance(day, CalendarDay) for day in self.memory_days):
            raise ReflectionContractError("Reflection availability days are invalid")
        if len(self.memory_days) != len(set(self.memory_days)):
            raise ReflectionContractError("Reflection availability days must be unique")
        object.__setattr__(self, "memory_days", tuple(sorted(self.memory_days)))
        if len(self.missing_daily_days) != len(set(self.missing_daily_days)) or not set(
            self.missing_daily_days
        ).issubset(self.memory_days):
            raise ReflectionContractError(
                "Missing daily days must be unique eligible days"
            )
        object.__setattr__(
            self, "missing_daily_days", tuple(sorted(self.missing_daily_days))
        )
        if self.next_before is not None and not isinstance(
            self.next_before, CalendarDay
        ):
            raise ReflectionContractError(
                "Reflection availability continuation must be a day"
            )
        if type(self.scanned_days) is not int or self.scanned_days < 0:
            raise ReflectionContractError(
                "Reflection availability scan count is invalid"
            )

    @property
    def home_pending(self) -> bool:
        return self.home_change_count > 0 or self.home_skill_memory_count > 0

    @property
    def memory_pending(self) -> bool:
        return bool(self.memory_days)

    @property
    def pending(self) -> bool:
        return self.home_pending or self.memory_pending

    def to_json(self) -> JsonObject:
        return {
            "checked_day": str(self.checked_day),
            "home_pending": self.home_pending,
            "home_change_count": self.home_change_count,
            "home_skill_memory_count": self.home_skill_memory_count,
            "memory_pending": self.memory_pending,
            "memory_days": [str(day) for day in self.memory_days],
            "missing_daily_days": [str(day) for day in self.missing_daily_days],
            "next_before": (
                str(self.next_before) if self.next_before is not None else None
            ),
            "scanned_days": self.scanned_days,
        }
