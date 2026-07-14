"""Typed Program work envelopes and non-persisted outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.json import JsonObject, to_json_object

from .day import BusinessDay
from .errors import LoopContractError


class ProgramWorkKind(StrEnum):
    HOME_MAINTENANCE = "home_maintenance"
    MEMORY_MAINTENANCE = "memory_maintenance"


class ProgramWorkMode(StrEnum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"


class ProgramWorkStatus(StrEnum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class ProgramWorkOutcome:
    """Bounded outcome retained only by the current Program run."""

    kind: ProgramWorkKind
    mode: ProgramWorkMode
    status: ProgramWorkStatus
    business_day: BusinessDay
    source: str = ""
    target_day: BusinessDay | None = None
    details: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProgramWorkKind):
            raise LoopContractError("Program work kind is invalid")
        if not isinstance(self.mode, ProgramWorkMode):
            raise LoopContractError("Program work mode is invalid")
        if not isinstance(self.status, ProgramWorkStatus):
            raise LoopContractError("Program work status is invalid")
        if not isinstance(self.business_day, BusinessDay):
            raise LoopContractError("Program work business_day is invalid")
        if self.target_day is not None and not isinstance(
            self.target_day,
            BusinessDay,
        ):
            raise LoopContractError("Program work target_day is invalid")
        if not isinstance(self.source, str):
            raise LoopContractError("Program work source must be text")
        object.__setattr__(self, "details", to_json_object(self.details))

    def to_json(self) -> JsonObject:
        value: JsonObject = {
            "kind": self.kind.value,
            "mode": self.mode.value,
            "status": self.status.value,
            "business_day": str(self.business_day),
            "source": self.source,
            "details": self.details,
        }
        if self.target_day is not None:
            value["target_day"] = str(self.target_day)
        return value
