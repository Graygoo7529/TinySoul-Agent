from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


from tinysoul.agent.commands import AgentCommands
from tinysoul.agent.dispatch.scheduler import RootScheduler

from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.interaction.inbox import TurnInbox
from tinysoul.plugins.archive import DailyTransitionOutcome
from tinysoul.plugins.reflection import (
    ReflectionAvailability,
    ReflectionRequest,
    ReflectionScope,
    ReflectionTrigger,
)
from tinysoul.runtime import SignalBus
from tinysoul.agent.lifecycle.runtime_policy import build_agent_trap


class _Work:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.inbox: TurnInbox | None = None

    async def run(
        self,
        turn_input,
        *,
        turn_id,
        active_day,
        scope,
        request_id,
        input_source,
        inbox=None,
    ):
        self.inbox = inbox
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("Test work only finishes by cancellation")


class _Reflection:
    @property
    def active_day(self):
        return self.current_day()

    def current_day(self):
        return CalendarDay.parse("2026-09-16")

    async def preflight(self, *, scope=None):
        return DailyTransitionOutcome(active_day=CalendarDay.parse("2026-09-16"))

    def availability(self):
        return ReflectionAvailability(checked_day=CalendarDay.parse("2026-09-16"))

    def refresh_availability(self, transition, *, scope):
        return self.availability()

    @asynccontextmanager
    async def active_day_lease(self):
        yield CalendarDay.parse("2026-09-16")

    async def run(self, request, *, turn_id, active_day, scope=None, inbox=None):
        raise AssertionError("Queued reflection must not start in this test")

    def allocate_turn(self, day):
        self._turn_sequence = getattr(self, "_turn_sequence", 0) + 1
        return f"{day}/{self._turn_sequence}"


async def test_daily_trigger_uses_calendar_day_before_rollover_and_deduplicates() -> (
    None
):
    reflection = _Reflection()
    root = RootScheduler(
        user_turn=_Work(),
        reflection=reflection,
        day=reflection,
        bus=SignalBus(),
        trap=build_agent_trap(),
    )
    commands = AgentCommands(root)
    first = await commands.request_reflection(
        ReflectionRequest(
            scope=ReflectionScope.DAILY,
            trigger=ReflectionTrigger.SCHEDULED,
        )
    )
    repeated = await commands.request_reflection(
        ReflectionRequest(
            scope=ReflectionScope.DAILY,
            trigger=ReflectionTrigger.SCHEDULED,
        )
    )
    assert first == repeated
    requests = tuple(
        item.request for item in first if isinstance(item.request, ReflectionRequest)
    )
    assert [item.scope for item in requests] == [
        ReflectionScope.HOME,
        ReflectionScope.MEMORY,
    ]
    assert requests[1].target_day == CalendarDay.parse("2026-09-15")
    assert len(root.queued_request_ids) == 2
    await root.close_requests()


