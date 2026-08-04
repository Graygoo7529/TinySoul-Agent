"""Typed Maintenance Turn boundary exposed to Maintenance tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.loop import TurnOutcomeStatus
from tinysoul.loop.turn import TurnOutcome
from tinysoul.runtime import RunLevel, RunScope, RuntimeTransferInterrupt

from ..errors import MaintenanceContractError


@dataclass(frozen=True)
class MaintenanceTurnResult:
    completed: bool
    details: JsonObject = field(default_factory=dict)


class MaintenanceTurnRunner(Protocol):
    def run(
        self,
        turn_input: str,
        *,
        business_day: BusinessDay,
        scope: RunScope,
        request_id: str,
        input_source: str,
    ) -> TurnOutcome: ...


class MaintenanceTurnEntry:
    """Own generic Turn outcome interpretation for one Maintenance task kind."""

    def __init__(self, runner: MaintenanceTurnRunner, *, kind: str) -> None:
        if kind not in {"home", "memory"}:
            raise MaintenanceContractError(f"Unknown Maintenance Turn kind: {kind}")
        self._runner = runner
        self._kind = kind

    def run(
        self,
        turn_input: str,
        *,
        business_day: BusinessDay,
        scope: RunScope,
        request_id: str,
        input_source: str,
    ) -> MaintenanceTurnResult:
        outcome = self._runner.run(
            turn_input,
            business_day=business_day,
            scope=scope,
            request_id=request_id,
            input_source=input_source,
        )
        self._propagate_outer_transfer(outcome)
        completed = (
            outcome.status is TurnOutcomeStatus.COMPLETED
            and outcome.completion is not None
            and outcome.completion.get("task") == self._kind
        )
        return MaintenanceTurnResult(
            completed=completed,
            details={} if completed else self._failure_details(outcome),
        )

    @staticmethod
    def _propagate_outer_transfer(outcome: TurnOutcome) -> None:
        transfer = outcome.transfer
        if transfer is not None and transfer.target.level is not RunLevel.TURN:
            raise RuntimeTransferInterrupt(transfer)

    @staticmethod
    def _failure_details(outcome: TurnOutcome) -> JsonObject:
        value: JsonObject = {"turn_status": outcome.status.value}
        if outcome.failure is not None:
            value.update(
                {
                    "failure_kind": outcome.failure.kind,
                    "failure_module": outcome.failure.module,
                    "failure_reason": outcome.failure.reason,
                }
            )
        return value
