from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from tinysoul.agent import AgentQueueFullError
from tinysoul.agent.commands import AgentCommands
from tinysoul.agent.requests import UserTurnRequest
from tinysoul.agent.scheduler import RootScheduler
from tinysoul.agent.inputs import InputCommandParser, InputDispatcher, InputEvent, InputIntentKind
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.inbox import TurnInbox
from tinysoul.plugins.archive import DailyTransitionOutcome
from tinysoul.plugins.reflection import (ReflectionAvailability, ReflectionRequest, ReflectionScope, ReflectionTrigger)
from tinysoul.runtime import SignalBus
from tinysoul.agent.runtime_policy import build_agent_trap


def test_input_parser_separates_user_and_active_turn_input() -> None:
    parser = InputCommandParser()
    assert parser.parse(InputEvent("hello"), turn_active=False).kind is InputIntentKind.USER_TURN
    assert parser.parse(InputEvent("more"), turn_active=True).kind is InputIntentKind.APPEND_INPUT


@pytest.mark.parametrize(("text", "kind"), [
    ("/maintenance", InputIntentKind.REJECTED),
    ("/maintenance home", InputIntentKind.MAINTENANCE),
    ("/maintenance memory 2026-07-12", InputIntentKind.MAINTENANCE),
    ("/maintenance memory tomorrow", InputIntentKind.REJECTED),
    ("/maintenance memory", InputIntentKind.REJECTED),
    ("/maintenance memory 2026-07-12 summarize knowledge", InputIntentKind.MAINTENANCE),
    ("/reply question A choice", InputIntentKind.REPLY),
    ("/grant budget 2", InputIntentKind.GRANT),
    ("/grant budget 0", InputIntentKind.REJECTED),
    ("/grant budget -1", InputIntentKind.REJECTED),
    ("/reply", InputIntentKind.REJECTED),
])
def test_parser_validates_command_arguments(text: str, kind: InputIntentKind) -> None:
    assert InputCommandParser().parse(InputEvent(text), turn_active=True).kind is kind


class _Work:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.inbox: TurnInbox | None = None

    async def run(self, turn_input, *, business_day, scope, request_id, input_source, inbox=None):
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

    async def run(self, request, *, business_day, scope=None, inbox=None):
        raise AssertionError("Queued reflection must not start in this test")


async def test_daily_trigger_uses_calendar_day_before_rollover_and_deduplicates() -> None:
    reflection = _Reflection()
    root = RootScheduler(user_turn=_Work(), maintenance=reflection, day=reflection,
                         bus=SignalBus(), trap=build_agent_trap())
    commands = AgentCommands(root)
    first = await commands.request_reflection(ReflectionRequest(
        scope=ReflectionScope.DAILY, trigger=ReflectionTrigger.SCHEDULED,
    ))
    repeated = await commands.request_reflection(ReflectionRequest(
        scope=ReflectionScope.DAILY, trigger=ReflectionTrigger.SCHEDULED,
    ))
    assert first == repeated
    requests = tuple(item.request for item in first if isinstance(item.request, ReflectionRequest))
    assert [item.scope for item in requests] == [ReflectionScope.HOME, ReflectionScope.MEMORY]
    assert requests[1].target_day == CalendarDay.parse("2026-09-15")
    assert len(root.queued_turn_ids) == 2
    await root.close_requests()


async def test_all_ingress_uses_bounded_roots_and_the_active_inbox() -> None:
    work = _Work()
    root = RootScheduler(user_turn=work, maintenance=_Reflection(), day=_Reflection(), bus=SignalBus(),
                         trap=build_agent_trap(), queue_capacity=1)
    commands = AgentCommands(root)
    dispatcher = InputDispatcher(parser=InputCommandParser(), commands=commands)
    first = await dispatcher.submit(InputEvent("hello", command_id="first"))
    full = await dispatcher.submit(InputEvent("too many"))
    assert first.accepted and not full.accepted and full.state == "full"
    worker = asyncio.create_task(root.run())
    try:
        await asyncio.wait_for(work.started.wait(), 2)
        assert work.inbox is not None
        more = await dispatcher.submit(InputEvent("more context", command_id="extra"))
        assert more.accepted
        batch = await work.inbox.capture()
        assert any(record.record_id == "extra" for _, record in batch.records)
        queued = await dispatcher.submit(InputEvent("/maintenance home", command_id="home"))
        assert queued.accepted
        reflection = commands.turn("home")
        assert reflection is not None and isinstance(reflection.request, ReflectionRequest)
        assert reflection.request.scope is ReflectionScope.HOME
        with pytest.raises(AgentQueueFullError):
            await commands.submit_turn(UserTurnRequest("also full"))
        exited = await dispatcher.submit(InputEvent("exit"))
        assert exited.accepted
        await asyncio.wait_for(worker, 2)
        assert (await reflection.wait()).status.value == "cancelled"
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        await root.close_requests()
