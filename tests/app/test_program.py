from __future__ import annotations

from contextlib import contextmanager
from queue import Queue

from tinysoul.app.program import ProgramRunner
from tinysoul.app.requests import AppRequest, ExitRequest, UserTurnRequest
from tinysoul.loop import TurnOutcomeStatus
from tinysoul.loop.trap_handlers import EndFrameTrapHandler
from tinysoul.loop.turn import TurnOutcome
from tinysoul.infra.time import BusinessDay
from tinysoul.maintenance import (
    DailyTransitionOutcome,
    MaintenanceAvailability,
    MaintenanceOutcome,
    MaintenanceRequest,
    MaintenanceScope,
    MaintenanceStatus,
    MaintenanceTrigger,
)
from tinysoul.runtime import (
    ObservationEvent,
    ObservationLevel,
    RUNTIME_PROGRAM_END,
    RunLevel,
    RuntimeTrap,
    SignalBus,
    TrapHandlerRegistry,
)


DAY = BusinessDay.parse("2026-08-03")


def test_program_dispatches_typed_requests_to_user_or_maintenance() -> None:
    queue: Queue[AppRequest] = Queue()
    user = _UserTurn()
    maintenance = _Maintenance()
    runner = ProgramRunner(
        user_turn=user,
        maintenance=maintenance,
        bus=SignalBus(),
        trap=_trap(),
        input_queue=queue,
    )
    queue.put(UserTurnRequest("hello", request_id="user_1"))
    queue.put(
        MaintenanceRequest(
            scope=MaintenanceScope.HOME,
            trigger=MaintenanceTrigger.MANUAL,
            request_id="maintenance_1",
        )
    )
    queue.put(ExitRequest(request_id="exit_1"))

    outcome = runner.run()

    assert user.inputs == ["hello"]
    assert [request.scope for request in maintenance.requests] == [
        MaintenanceScope.HOME
    ]
    assert outcome.turn_count == 1
    assert outcome.maintenance_count == 1
    assert len(outcome.turns) == 1
    assert len(outcome.maintenance) == 1


def test_program_startup_reports_complete_maintenance_availability() -> None:
    queue: Queue[AppRequest] = Queue()
    queue.put(ExitRequest(request_id="exit_1"))
    maintenance = _Maintenance(
        availability=MaintenanceAvailability(
            checked_day=DAY,
            home_change_count=2,
            home_skill_memory_count=1,
            memory_days=(
                BusinessDay.parse("2026-08-01"),
                BusinessDay.parse("2026-08-02"),
            ),
        )
    )
    observations = _RecordingObservations()
    runner = ProgramRunner(
        user_turn=_UserTurn(),
        maintenance=maintenance,
        bus=SignalBus(),
        trap=_trap(),
        input_queue=queue,
        observations=observations,
    )

    runner.run()

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

    def run(self, turn_input, *, business_day, scope, request_id, input_source):
        del scope, request_id, input_source
        self.inputs.append(turn_input)
        return TurnOutcome(
            context_completion=None,
            business_day=business_day,
            status=TurnOutcomeStatus.STOPPED,
        )


class _Maintenance:
    def __init__(self, *, availability: MaintenanceAvailability | None = None) -> None:
        self.requests: list[MaintenanceRequest] = []
        self._availability = availability or MaintenanceAvailability(checked_day=DAY)

    def preflight(self, *, scope=None):
        del scope
        return DailyTransitionOutcome(active_day=DAY)

    def availability(self):
        return self._availability

    @contextmanager
    def active_day_lease(self):
        yield DAY

    def run(self, request, *, scope=None):
        del scope
        self.requests.append(request)
        return MaintenanceOutcome(
            request_id=request.request_id,
            business_day=DAY,
            status=MaintenanceStatus.SKIPPED,
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
    registry.register(RUNTIME_PROGRAM_END, EndFrameTrapHandler(RunLevel.PROGRAM))
    return RuntimeTrap(registry=registry)
