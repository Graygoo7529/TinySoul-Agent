"""Typed Maintenance requests accepted by the App queue."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4

from tinysoul.infra.json import JsonObject, to_json_object

from .day import BusinessDay
from .errors import MaintenanceContractError


class MaintenanceScope(StrEnum):
    DAILY = "daily"
    HOME = "home"
    MEMORY = "memory"


class MaintenanceTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


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
        if self.scope is MaintenanceScope.HOME and self.target_day is not None:
            raise MaintenanceContractError("Home Maintenance cannot target a day")
        if not isinstance(self.rebuild_memory, bool):
            raise MaintenanceContractError("Maintenance rebuild_memory must be boolean")
        if self.scope is MaintenanceScope.HOME and self.rebuild_memory:
            raise MaintenanceContractError("Home Maintenance cannot rebuild Memory")
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
