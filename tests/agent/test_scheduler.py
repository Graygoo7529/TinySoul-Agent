from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from threading import Event
import pytest

from tinysoul.agent.scheduler import RootScheduler
from tinysoul.agent.requests import AgentRequest, ExitRequest, UserTurnRequest
from tinysoul.kernel.loop import TurnOutcomeStatus
from tinysoul.kernel.loop.trap_handlers import EndFrameTrapHandler
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.archive import DailyTransitionOutcome
from tinysoul.plugins.archive.errors import ArchiveInvariantError
from tinysoul.plugins.archive.runtime_bridge import RuntimeArchiveBridge
from tinysoul.plugins.reflection import (ReflectionAvailability, ReflectionOutcome, ReflectionRequest, ReflectionScope, ReflectionStatus, ReflectionTrigger)
from tinysoul.runtime import (
    ObservationEvent,
    ObservationLevel,
    RUNTIME_AGENT_END,
    RunLevel,
    RuntimeTrap,
    SignalBus,
    TrapHandlerRegistry,
)


DAY = CalendarDay.parse("2026-08-03")


async def test_day_preparation_yields_and_joins_before_cancellation() -> None:
    entered, release, finished = Event(), Event(), Event()

    class Day(_Reflection):
        async def preflight(self, *, scope=None):
            entered.set()
            from tinysoul.infra.concurrency import JoinedOperations
            operations = JoinedOperations()
            assert await operations.run(lambda: release.wait(3))
            finished.set()
            operations.check_cancelled()
            return await super().preflight(scope=scope)

    day = Day()
    runner = RootScheduler(user_turn=_UserTurn(), maintenance=day, day=day,
                           bus=SignalBus(), trap=_trap())
    worker = asyncio.create_task(runner.prepare())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        worker.cancel()
        await asyncio.sleep(0)
        assert not worker.done() and not finished.is_set()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await worker
    assert finished.is_set()


async def test_day_failure_at_request_boundary_enters_agent_trap() -> None:
    class Day(_Reflection):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def preflight(self, *, scope=None):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeArchiveBridge().from_archive_error(ArchiveInvariantError("private location"))
            return await super().preflight(scope=scope)

    day = Day()
    user = _UserTurn()
    runner = RootScheduler(user_turn=user, maintenance=day, day=day, bus=SignalBus(), trap=_trap())
    handle = runner.submit_turn(UserTurnRequest("cannot start"))
    outcome = await runner.run()
    assert outcome.transfer is not None and outcome.transfer.target.level is RunLevel.AGENT
    assert not user.inputs and (await handle.wait()).status.value == "failed"


async def test_program_dispatches_typed_requests_to_user_or_maintenance() -> None:
    user = _UserTurn()
    maintenance = _Reflection()
    runner = RootScheduler(
        user_turn=user,
        maintenance=maintenance,
        day=maintenance,
        bus=SignalBus(),
        trap=_trap(),
    )
    user_handle = runner.submit_turn(UserTurnRequest("hello", request_id="user_1"))
    reflection = runner.submit_turn(
        ReflectionRequest(
            scope=ReflectionScope.HOME,
            trigger=ReflectionTrigger.MANUAL,
            request_id="maintenance_1",
        )
    )
    worker = asyncio.create_task(runner.run())
    await user_handle.wait()
    await reflection.wait()
    runner.request_exit(ExitRequest(request_id="exit_1"))
    outcome = await worker

    assert user.inputs == ["hello"]
    assert [request.scope for request in maintenance.requests] == [
        ReflectionScope.HOME
    ]
    assert outcome.turn_count == 1
    assert outcome.maintenance_count == 1
    assert len(outcome.turns) == 1
    assert len(outcome.maintenance) == 1


async def test_queued_cancellations_release_capacity_and_retain_by_completion_order() -> None:
    user, maintenance = _UserTurn(), _Reflection()
    runner = RootScheduler(
        user_turn=user, maintenance=maintenance, day=maintenance,
        bus=SignalBus(), trap=_trap(), retained_outcomes=2,
    )
    runner.set_capacity(1)
    cancelled = []
    for index in range(8):
        handle = runner.submit_turn(UserTurnRequest("cancel before execution", request_id=f"queued_{index}"))
        assert await runner.cancel_turn(handle.turn_id)
        assert runner.queued_turn_ids == ()
        cancelled.append(handle)
    assert all(runner.turn_handle(handle.turn_id) is None for handle in cancelled[:-2])
    assert all(runner.turn_handle(handle.turn_id) is handle for handle in cancelled[-2:])
    for handle in cancelled:
        assert (await handle.wait()).status.value == "cancelled"
    active = runner.submit_turn(UserTurnRequest("only this executes", request_id="final"))
    worker = asyncio.create_task(runner.run())
    await asyncio.wait_for(active.wait(), 3)
    runner.request_exit(ExitRequest(request_id="exit"))
    await asyncio.wait_for(worker, 3)
    assert user.inputs == ["only this executes"]
    assert runner.turn_handle(cancelled[-2].turn_id) is None


async def test_program_startup_reports_complete_maintenance_availability() -> None:
    maintenance = _Reflection(
        availability=ReflectionAvailability(
            checked_day=DAY,
            home_change_count=2,
            home_skill_memory_count=1,
            memory_days=(
                CalendarDay.parse("2026-08-01"),
                CalendarDay.parse("2026-08-02"),
            ),
        )
    )
    observations = _RecordingObservations()
    runner = RootScheduler(
        user_turn=_UserTurn(),
        maintenance=maintenance,
        day=maintenance,
        bus=SignalBus(),
        trap=_trap(),
        observations=observations,
    )

    runner.request_exit(ExitRequest(request_id="exit_1"))
    await runner.run()

    event = next(
        event
        for event in observations.events
        if event.name == "program.maintenance.available"
    )
    assert event.payload == maintenance.availability().to_json()
    assert event.payload["home_pending"] is True
    assert event.payload["memory_days"] == ["2026-08-01", "2026-08-02"]


class _UserTurn:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def run(self, turn_input, *, business_day, scope, request_id, input_source, inbox=None):
        del scope, request_id, input_source
        self.inputs.append(turn_input)
        return TurnOutcome(
            context_completion=None,
            business_day=business_day,
            status=TurnOutcomeStatus.STOPPED,
        )


class _Reflection:
    def __init__(self, *, availability: ReflectionAvailability | None = None) -> None:
        self.requests: list[ReflectionRequest] = []
        self._availability = availability or ReflectionAvailability(checked_day=DAY)

    @property
    def active_day(self):
        return self.current_day()

    def current_day(self):
        return DAY

    async def preflight(self, *, scope=None):
        del scope
        return DailyTransitionOutcome(active_day=DAY)

    def availability(self):
        return self._availability

    def refresh_availability(self, transition, *, scope):
        return self.availability()

    @asynccontextmanager
    async def active_day_lease(self):
        yield DAY

    async def run(self, request, *, business_day, scope=None, inbox=None):
        del scope
        self.requests.append(request)
        return ReflectionOutcome(
            request_id=request.request_id,
            business_day=DAY,
            status=ReflectionStatus.SKIPPED,
        )


class _RecordingObservations:
    def __init__(self) -> None:
        self.events: list[ObservationEvent] = []

    def enabled(self, level: ObservationLevel) -> bool:
        del level
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)


def _trap() -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_AGENT_END, EndFrameTrapHandler(RunLevel.AGENT))
    return RuntimeTrap(registry=registry)
