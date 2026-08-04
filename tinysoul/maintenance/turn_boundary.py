"""Maintenance Task handling for reusable Turn outcomes."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject
from tinysoul.loop.turn import TurnOutcome
from tinysoul.runtime import RunLevel, RuntimeTransferInterrupt


def propagate_outer_turn_transfer(outcome: TurnOutcome) -> None:
    """Unwind every transfer that is not owned by the completed Turn."""

    transfer = outcome.transfer
    if transfer is not None and transfer.target.level is not RunLevel.TURN:
        raise RuntimeTransferInterrupt(transfer)


def turn_failure_details(outcome: TurnOutcome) -> JsonObject:
    """Project one Turn-local failure into a bounded task outcome payload."""

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
