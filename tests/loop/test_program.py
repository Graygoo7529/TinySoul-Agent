from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

from tinysoul.loop import (
    BusinessClock,
    BusinessDay,
    DailyLifecycleCoordinator,
    ProgramInputEvent,
    ProgramRunner,
    ProgramWorkKind,
    ProgramWorkMode,
    ProgramWorkOutcome,
    ProgramWorkStatus,
    TurnOutcome,
    TurnOutput,
    TurnOutcomeStatus,
    TurnRunner,
)
from tinysoul.loop.maintenance import MaintenanceAvailability, ProgramMaintenanceRunner
from tinysoul.runtime import (
    RUNTIME_PROGRAM_END,
    RunLevel,
    RunScope,
    RuntimeTransfer,
    RuntimeTransferAction,
    RuntimeTrap,
    SignalBus,
    TrapHandlerRegistry,
    TrapResult,
    TrapSnap,
)


@dataclass
class _FakeTurnRunner:
    inputs: list[str] = field(default_factory=list)
    days: list[BusinessDay] = field(default_factory=list)
    requests: list[tuple[str, str]] = field(default_factory=list)

    def run(
        self,
        user_input: str,
        *,
        business_day: BusinessDay,
        scope: RunScope,
        request_id: str = "",
        input_source: str = "",
    ) -> TurnOutcome:
        self.inputs.append(user_input)
        self.days.append(business_day)
        self.requests.append((request_id, input_source))
        return TurnOutcome(
            context_completion=None,
            business_day=business_day,
            status=TurnOutcomeStatus.ANSWERED,
            output=TurnOutput(text="done", result_id="answer_1"),
        )


@dataclass
class _FakeDailyLifecycle:
    days: list[BusinessDay] = field(default_factory=list)

    def ensure_active_day(
        self,
        day: BusinessDay,
        *,
        now: datetime,
        scope: RunScope | None = None,
    ) -> None:
        self.days.append(day)


@dataclass
class _FakeMaintenanceRunner:
    home_status: ProgramWorkStatus = ProgramWorkStatus.COMPLETED
    memory_status: ProgramWorkStatus = ProgramWorkStatus.COMPLETED
    home_calls: list[tuple[BusinessDay, ProgramWorkMode, str]] = field(
        default_factory=list
    )
    memory_calls: list[
        tuple[BusinessDay, BusinessDay, ProgramWorkMode, str]
    ] = field(default_factory=list)

    def availability(self, business_day: BusinessDay) -> MaintenanceAvailability:
        return MaintenanceAvailability(
            home_pending=False,
            home_change_count=0,
            home_skill_memory_count=0,
            memory_pending=False,
            memory_day=BusinessDay.parse("2026-07-11"),
        )

    def run_home(
        self,
        *,
        business_day: BusinessDay,
        mode: ProgramWorkMode,
        source: str,
        scope: RunScope,
    ) -> ProgramWorkOutcome:
        self.home_calls.append((business_day, mode, source))
        return ProgramWorkOutcome(
            kind=ProgramWorkKind.HOME_MAINTENANCE,
            mode=mode,
            status=self.home_status,
            business_day=business_day,
            source=source,
        )

    def run_memory(
        self,
        *,
        business_day: BusinessDay,
        target_day: BusinessDay,
        mode: ProgramWorkMode,
        source: str,
        scope: RunScope,
    ) -> ProgramWorkOutcome:
        self.memory_calls.append((business_day, target_day, mode, source))
        return ProgramWorkOutcome(
            kind=ProgramWorkKind.MEMORY_MAINTENANCE,
            mode=mode,
            status=self.memory_status,
            business_day=business_day,
            target_day=target_day,
            source=source,
        )


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 12, 12, tzinfo=ZoneInfo("Asia/Shanghai"))

    def today(self) -> BusinessDay:
        return BusinessDay.parse("2026-07-12")


@dataclass
class _SequenceClock:
    values: list[datetime]

    def now(self) -> datetime:
        return self.values.pop(0)

    def today(self) -> BusinessDay:
        return BusinessDay(self.values[0].date())


@dataclass
class _ProgramEndHandler:
    snaps: list[TrapSnap] = field(default_factory=list)

    def handle(self, snap: TrapSnap) -> TrapResult:
        self.snaps.append(snap)
        frame = snap.scope.nearest(RunLevel.PROGRAM)
        assert frame is not None
        return TrapResult(transfer=RuntimeTransfer.end(frame))


def test_program_runner_starts_turn_from_program_input_event() -> None:
    fake_turn_runner = _FakeTurnRunner()
    handler = _ProgramEndHandler()
    runner = ProgramRunner(
        turn_runner=cast(TurnRunner, fake_turn_runner),
        bus=SignalBus(),
        trap=_trap(handler),
        daily_lifecycle=cast(DailyLifecycleCoordinator, _FakeDailyLifecycle()),
        business_clock=cast(BusinessClock, _FixedClock()),
    )

    runner.submit_event(ProgramInputEvent.start_turn("hello"))
    runner.submit_event(ProgramInputEvent.exit_program(text="exit"))
    outcome = runner.run()

    assert fake_turn_runner.inputs == ["hello"]
    assert len(outcome.turns) == 1
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.PROGRAM


def test_program_runner_exit_event_ends_program_without_turn() -> None:
    fake_turn_runner = _FakeTurnRunner()
    handler = _ProgramEndHandler()
    runner = ProgramRunner(
        turn_runner=cast(TurnRunner, fake_turn_runner),
        bus=SignalBus(),
        trap=_trap(handler),
        daily_lifecycle=cast(DailyLifecycleCoordinator, _FakeDailyLifecycle()),
        business_clock=cast(BusinessClock, _FixedClock()),
    )

    runner.submit_event(
        ProgramInputEvent.exit_program(
            text="bye",
            source="test",
            metadata={"reason": "unit"},
            request_id="command_exit",
        )
    )
    outcome = runner.run()

    assert fake_turn_runner.inputs == []
    assert outcome.turns == ()
    assert outcome.transfer is not None
    assert handler.snaps[0].payload == {
        "input": "bye",
        "source": "test",
        "metadata": {"reason": "unit"},
        "request_id": "command_exit",
    }


def test_program_runner_bounds_retained_outcomes_but_counts_all_turns() -> None:
    fake_turn_runner = _FakeTurnRunner()
    handler = _ProgramEndHandler()
    runner = ProgramRunner(
        turn_runner=cast(TurnRunner, fake_turn_runner),
        bus=SignalBus(),
        trap=_trap(handler),
        daily_lifecycle=cast(DailyLifecycleCoordinator, _FakeDailyLifecycle()),
        business_clock=cast(BusinessClock, _FixedClock()),
        retained_outcomes=2,
    )
    for text in ("one", "two", "three"):
        runner.submit_event(ProgramInputEvent.start_turn(text))
    runner.submit_event(ProgramInputEvent.exit_program(text="exit"))

    outcome = runner.run()

    assert fake_turn_runner.inputs == ["one", "two", "three"]
    assert outcome.turn_count == 3
    assert len(outcome.turns) == 2


def test_program_runner_executes_typed_maintenance_independently_from_turns() -> None:
    fake_turn_runner = _FakeTurnRunner()
    lifecycle = _FakeDailyLifecycle()
    maintenance = _FakeMaintenanceRunner(
        home_status=ProgramWorkStatus.FAILED,
    )
    handler = _ProgramEndHandler()
    runner = ProgramRunner(
        turn_runner=cast(TurnRunner, fake_turn_runner),
        bus=SignalBus(),
        trap=_trap(handler),
        daily_lifecycle=cast(DailyLifecycleCoordinator, lifecycle),
        maintenance_runner=cast(ProgramMaintenanceRunner, maintenance),
        business_clock=cast(BusinessClock, _FixedClock()),
        retained_outcomes=1,
    )

    runner.submit_event(
        ProgramInputEvent.home_maintenance(
            mode=ProgramWorkMode.AUTOMATIC,
            source="scheduler",
        )
    )
    runner.submit_event(
        ProgramInputEvent.memory_maintenance(
            mode=ProgramWorkMode.MANUAL,
            source="terminal",
        )
    )
    runner.submit_event(ProgramInputEvent.start_turn("continue after work failure"))
    runner.submit_event(ProgramInputEvent.exit_program(text="exit"))

    outcome = runner.run()

    day = BusinessDay.parse("2026-07-12")
    yesterday = BusinessDay.parse("2026-07-11")
    assert maintenance.home_calls == [(day, ProgramWorkMode.AUTOMATIC, "scheduler")]
    assert maintenance.memory_calls == [
        (day, yesterday, ProgramWorkMode.MANUAL, "terminal")
    ]
    assert fake_turn_runner.inputs == ["continue after work failure"]
    assert outcome.work_count == 2
    assert len(outcome.works) == 1
    assert outcome.works[0].kind is ProgramWorkKind.MEMORY_MAINTENANCE
    assert outcome.turn_count == 1
    assert lifecycle.days == [day, day, day, day]


def test_program_switches_business_day_only_between_turns() -> None:
    fake_turn_runner = _FakeTurnRunner()
    lifecycle = _FakeDailyLifecycle()
    timezone = ZoneInfo("Asia/Shanghai")
    clock = _SequenceClock(
        [
            datetime(2026, 7, 11, 23, 59, 59, tzinfo=timezone),
            datetime(2026, 7, 12, 0, 0, 1, tzinfo=timezone),
        ]
    )
    handler = _ProgramEndHandler()
    runner = ProgramRunner(
        turn_runner=cast(TurnRunner, fake_turn_runner),
        bus=SignalBus(),
        trap=_trap(handler),
        daily_lifecycle=cast(DailyLifecycleCoordinator, lifecycle),
        business_clock=cast(BusinessClock, clock),
    )

    first = runner.run_once("before midnight")
    second = runner.run_once("after midnight")

    assert first.business_day == BusinessDay.parse("2026-07-11")
    assert second.business_day == BusinessDay.parse("2026-07-12")
    assert lifecycle.days == [first.business_day, second.business_day]
    assert fake_turn_runner.days == lifecycle.days


def _trap(handler: _ProgramEndHandler) -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_PROGRAM_END, handler)
    return RuntimeTrap(registry=registry)
