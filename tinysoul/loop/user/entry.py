"""Lightweight User Turn entry exposed to App Program dispatch."""

from __future__ import annotations

from tinysoul.infra.time import BusinessDay
from tinysoul.runtime import RunScope

from ..turn import TurnOutcome, TurnRunner


class UserTurnEntry:
    def __init__(self, runner: TurnRunner) -> None:
        self._runner = runner

    @property
    def active_scope(self) -> RunScope | None:
        return self._runner.active_scope

    def run(
        self,
        turn_input: str,
        *,
        business_day: BusinessDay,
        scope: RunScope,
        request_id: str = "",
        input_source: str = "",
    ) -> TurnOutcome:
        return self._runner.run(
            turn_input,
            business_day=business_day,
            scope=scope,
            request_id=request_id,
            input_source=input_source,
        )
