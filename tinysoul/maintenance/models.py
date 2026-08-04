"""Typed requests, plans, availability, and outcomes for Maintenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from tinysoul.infra.json import JsonObject, to_json_object

from tinysoul.infra.time import BusinessDay
from .errors import MaintenanceContractError


class MaintenanceScope(StrEnum):
    DAILY = "daily"
    HOME = "home"
    MEMORY = "memory"


class MaintenanceTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class MaintenanceTaskKind(StrEnum):
    ARCHIVE = "archive"
    HOME = "home"
    MEMORY = "memory"


class MaintenanceTaskStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class MaintenanceStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class MaintenanceRequest:
    scope: MaintenanceScope
    trigger: MaintenanceTrigger
    target_day: BusinessDay | None = None
    rebuild_memory: bool = False
    source: str = ""
    request_id: str = field(default_factory=lambda: f"request_{uuid4().hex}")
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, MaintenanceScope):
            raise MaintenanceContractError("Maintenance request scope is invalid")
        if not isinstance(self.trigger, MaintenanceTrigger):
            raise MaintenanceContractError("Maintenance request trigger is invalid")
        if self.target_day is not None and not isinstance(self.target_day, BusinessDay):
            raise MaintenanceContractError("Maintenance request target_day is invalid")
        if self.scope is not MaintenanceScope.MEMORY and self.target_day is not None:
            raise MaintenanceContractError(
                "Only Memory Maintenance can target an explicit day"
            )
        if self.scope is MaintenanceScope.MEMORY and self.target_day is None:
            raise MaintenanceContractError(
                "Memory Maintenance requires an explicit target day"
            )
        if not isinstance(self.rebuild_memory, bool):
            raise MaintenanceContractError("Maintenance rebuild_memory must be boolean")
        if self.scope is not MaintenanceScope.MEMORY and self.rebuild_memory:
            raise MaintenanceContractError(
                "Only Memory Maintenance can request a rebuild"
            )
        if not isinstance(self.source, str):
            raise MaintenanceContractError("Maintenance request source must be text")
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise MaintenanceContractError("Maintenance request_id must be non-empty")
        object.__setattr__(self, "request_id", self.request_id.strip())
        object.__setattr__(self, "metadata", to_json_object(self.metadata))

    def to_json(self) -> JsonObject:
        value: JsonObject = {
            "scope": self.scope.value,
            "trigger": self.trigger.value,
            "rebuild_memory": self.rebuild_memory,
            "source": self.source,
            "request_id": self.request_id,
            "metadata": self.metadata,
        }
        if self.target_day is not None:
            value["target_day"] = str(self.target_day)
        return value


@dataclass(frozen=True)
class MaintenanceTaskOutcome:
    kind: MaintenanceTaskKind
    status: MaintenanceTaskStatus
    target_day: BusinessDay | None = None
    reason: str = ""
    details: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MaintenanceTaskKind):
            raise MaintenanceContractError("Maintenance task kind is invalid")
        if not isinstance(self.status, MaintenanceTaskStatus):
            raise MaintenanceContractError("Maintenance task status is invalid")
        if self.target_day is not None and not isinstance(self.target_day, BusinessDay):
            raise MaintenanceContractError("Maintenance task target_day is invalid")
        if not isinstance(self.reason, str):
            raise MaintenanceContractError("Maintenance task reason must be text")
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
        return value


@dataclass(frozen=True)
class MaintenanceOutcome:
    request_id: str
    business_day: BusinessDay
    status: MaintenanceStatus
    tasks: tuple[MaintenanceTaskOutcome, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id:
            raise MaintenanceContractError("Maintenance outcome request_id is invalid")
        if not isinstance(self.business_day, BusinessDay):
            raise MaintenanceContractError("Maintenance outcome business_day is invalid")
        if not isinstance(self.status, MaintenanceStatus):
            raise MaintenanceContractError("Maintenance outcome status is invalid")
        if any(not isinstance(item, MaintenanceTaskOutcome) for item in self.tasks):
            raise MaintenanceContractError("Maintenance outcome tasks are invalid")
        object.__setattr__(self, "tasks", tuple(self.tasks))

    def to_json(self) -> JsonObject:
        return {
            "request_id": self.request_id,
            "business_day": str(self.business_day),
            "status": self.status.value,
            "tasks": [task.to_json() for task in self.tasks],
        }


@dataclass(frozen=True)
class MaintenanceAvailability:
    checked_day: BusinessDay
    home_change_count: int = 0
    home_skill_memory_count: int = 0
    memory_days: tuple[BusinessDay, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.checked_day, BusinessDay):
            raise MaintenanceContractError("Maintenance availability checked day is invalid")
        for value in (self.home_change_count, self.home_skill_memory_count):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MaintenanceContractError(
                    "Maintenance availability counts must be non-negative integers"
                )
        if any(not isinstance(day, BusinessDay) for day in self.memory_days):
            raise MaintenanceContractError("Maintenance availability days are invalid")
        if len(self.memory_days) != len(set(self.memory_days)):
            raise MaintenanceContractError("Maintenance availability days must be unique")
        object.__setattr__(self, "memory_days", tuple(sorted(self.memory_days)))

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
        }
