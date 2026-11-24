"""Typed Reflection Turn boundary exposed to Reflection tasks."""

from __future__ import annotations

from typing import Protocol

from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.kernel.loop.interaction.inbox import TurnInbox
from tinysoul.runtime import RunLevel, RunScope, RuntimeTransferInterrupt


class ReflectionTurnRunner(Protocol):
    async def run(
        self,
        turn_input: str,
        *,
        active_day: CalendarDay,
        scope: RunScope,
        request_id: str,
        turn_id: str,
        input_source: str,
        inbox: TurnInbox | None = None,
    ) -> TurnOutcome: ...


class ReflectionTurnEntry:
    """Propagate outer transfers from the shared Reflection Turn kernel."""

    def __init__(self, runner: ReflectionTurnRunner) -> None:
        self._runner = runner

    async def run(
        self,
        turn_input: str,
        *,
        active_day: CalendarDay,
        scope: RunScope,
        request_id: str,
        turn_id: str,
        input_source: str,
        inbox: TurnInbox | None = None,
    ) -> TurnOutcome:
        outcome = await self._runner.run(
            turn_input,
            active_day=active_day,
            scope=scope,
            request_id=request_id,
            turn_id=turn_id,
            input_source=input_source,
            inbox=inbox,
        )
        self._propagate_outer_transfer(outcome)
        return outcome

    @staticmethod
    def _propagate_outer_transfer(outcome: TurnOutcome) -> None:
        transfer = outcome.transfer
        if transfer is not None and transfer.target.level is not RunLevel.TURN:
            raise RuntimeTransferInterrupt(transfer)
