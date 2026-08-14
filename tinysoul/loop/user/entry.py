"""Lightweight User Turn entry exposed to App Program dispatch."""

from __future__ import annotations

from tinysoul.action import ActionEngine
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.runtime import RunScope

from ..signals import LoopControlKind
from ..turn import TurnOutcome, TurnRunner


class UserTurnEntry:
    def __init__(self, runner: TurnRunner, *, action: ActionEngine) -> None:
        self._runner = runner
        self._action = action

    @property
    def active_scope(self) -> RunScope | None:
        return self._runner.active_scope

    def request_cancel(self, kind: LoopControlKind) -> bool:
        """Fire the active Turn's cooperative cancel token, if any."""

        return self._runner.request_active_cancel(kind)

    def action_catalog(self) -> JsonObject:
        """Return configured User Actions with current availability."""

        return self._action.catalog_json()

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
