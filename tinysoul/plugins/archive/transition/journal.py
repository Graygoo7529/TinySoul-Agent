"""Archive owner: deterministic rollover journal and frozen-day catalog."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay, CalendarDayError

from ..errors import ArchiveContractError


class DailyTransitionStep(StrEnum):
    SESSION_ARCHIVED = "session_archived"
    WORKSPACE_ARCHIVED = "workspace_archived"
    ACTIVE_INITIALIZED = "active_initialized"


@dataclass(frozen=True)
class DailyTransitionJournal:
    operation_id: str
    from_day: str
    to_day: str
    archive_name: str
    started_at: str
    completed_steps: tuple[DailyTransitionStep, ...] = field(default_factory=tuple)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ArchiveContractError("Daily journal schema_version must be 1")
        if not self.operation_id or not self.archive_name or not self.started_at:
            raise ArchiveContractError(
                "Daily journal identity fields must be non-empty"
            )
        try:
            CalendarDay.parse(self.from_day)
            CalendarDay.parse(self.to_day)
        except CalendarDayError as exc:
            raise ArchiveContractError("Daily journal contains an invalid day") from exc
        steps = tuple(self.completed_steps)
        if len(steps) != len(set(steps)):
            raise ArchiveContractError("Daily journal steps must be unique")
        object.__setattr__(self, "completed_steps", steps)

    def completed(self, step: DailyTransitionStep) -> bool:
        return step in self.completed_steps

    def with_step(self, step: DailyTransitionStep) -> "DailyTransitionJournal":
        if self.completed(step):
            return self
        return replace(self, completed_steps=(*self.completed_steps, step))

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "from_day": self.from_day,
            "to_day": self.to_day,
            "archive_name": self.archive_name,
            "started_at": self.started_at,
            "completed_steps": [step.value for step in self.completed_steps],
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "DailyTransitionJournal":
        expected_fields = {
            "schema_version",
            "operation_id",
            "from_day",
            "to_day",
            "archive_name",
            "started_at",
            "completed_steps",
        }
        if set(value) != expected_fields:
            raise ArchiveContractError("Daily journal fields are invalid")
        steps_value = value.get("completed_steps", [])
        if not isinstance(steps_value, list):
            raise ArchiveContractError("Daily journal completed_steps must be a list")
        try:
            steps = tuple(DailyTransitionStep(item) for item in steps_value)
        except (TypeError, ValueError) as exc:
            raise ArchiveContractError(
                "Daily journal contains an unknown step"
            ) from exc
        return cls(
            schema_version=_required_int(value, "schema_version"),
            operation_id=_required_str(value, "operation_id"),
            from_day=_required_str(value, "from_day"),
            to_day=_required_str(value, "to_day"),
            archive_name=_required_str(value, "archive_name"),
            started_at=_required_str(value, "started_at"),
            completed_steps=steps,
        )


def _required_str(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise ArchiveContractError(f"Daily journal field must be text: {name}")
    return item


def _required_int(value: JsonObject, name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ArchiveContractError(f"Daily journal field must be int: {name}")
    return item
