"""Lightweight User Turn entry exposed to App Program dispatch."""

from __future__ import annotations

from tinysoul.kernel.action import ActionEngine
from tinysoul.kernel.loop.assembly import TurnProfile
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.runtime import RunScope

from tinysoul.kernel.loop.signals import LoopControlKind
from tinysoul.kernel.loop.interaction.inbox import TurnInbox
from tinysoul.kernel.loop.turn import TurnOutcome, TurnRunner


class UserTurnEntry:
    def __init__(self, runner: TurnRunner, *, profile: TurnProfile) -> None:
        self._runner = runner
        self.profile = profile

    @property
    def active_scope(self) -> RunScope | None:
        return self._runner.active_scope

    def request_cancel(self, kind: LoopControlKind) -> bool:
        """Fire the active Turn's cooperative cancel token, if any."""

        return self._runner.request_active_cancel(kind)

    def action_catalog(self) -> JsonObject:
        """Return configured User Actions with current availability."""

        return self.profile.action.catalog_json()

    @property
    def action_engine(self) -> ActionEngine:
        """Expose the profile's action facade to generation assembly."""
        return self.profile.action

    async def run(
        self,
        turn_input: str,
        *,
        business_day: CalendarDay,
        scope: RunScope,
        request_id: str = "",
        input_source: str = "",
        inbox: TurnInbox | None = None,
    ) -> TurnOutcome:
        return await self._runner.run(
            turn_input,
            business_day=business_day,
            scope=scope,
            request_id=request_id,
            input_source=input_source,
            inbox=inbox,
        )
