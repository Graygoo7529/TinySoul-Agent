"""Bounded outcomes for one Maintenance request."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object

from .day import BusinessDay
from .errors import MaintenanceContractError


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
