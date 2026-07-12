from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from tinysoul.context import ContextEngine, ContextEngineBuilder
from tinysoul.context.errors import ContextContractError
from tinysoul.loop import BusinessDay, LoopSettings, TurnOutcomeStatus
from tinysoul.loop import (
    TurnCompletion,
    TurnCompletionPipeline,
    TurnOutput,
    TurnPreparationPipeline,
    TurnPreparationRequest,
    build_turn_output_signal,
)
from tinysoul.loop.cycle import CycleOutcome, CycleRunner
from tinysoul.loop.trap_handlers import EndFrameTrapHandler
from tinysoul.loop.turn import TurnRunner
from tinysoul.runtime import (
    ObservationEvent,
    ObservationLevel,
    RUNTIME_TURN_END,
    RunLevel,
    RunScope,
    RuntimeTransfer,
    RuntimeTransferAction,
    RuntimeTransferInterrupt,
    RuntimeException,
    RuntimeTrap,
    Signal,
    SignalBus,
    TrapHandlerRegistry,
)


DAY = BusinessDay.parse("2026-07-12")


@dataclass
class _EndFailingContext:
    active: bool = False
    aborted: int = 0

    @property
    def turn_active(self) -> bool:
        return self.active

    def begin_turn(self, user_input: str) -> str:
        self.active = True
        return "turn_1"

    def complete_preparation(self) -> None:
        pass

    def end_turn(self) -> object:
        raise ContextContractError("summary failed")

    def abort_turn(self) -> None:
        self.active = False
        self.aborted += 1

    def consume_signals(self, bus: SignalBus) -> tuple[object, ...]:
        return ()


class _AnsweredCycleRunner:
    def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
    ) -> CycleOutcome:
        frame = scope.nearest(RunLevel.TURN)
        assert frame is not None
        return CycleOutcome(
            cycle_id=f"cycle_{cycle_index}",
            transfer=RuntimeTransfer.end(frame),
        )


class _ProgramEndCycleRunner:
    def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
    ) -> CycleOutcome:
        frame = scope.nearest(RunLevel.PROGRAM)
        assert frame is not None
        return CycleOutcome(
            cycle_id=f"cycle_{cycle_index}",
            transfer=RuntimeTransfer.end(frame),
        )


@dataclass
class _CountingCycleRunner:
    calls: int = 0

    def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
    ) -> CycleOutcome:
        self.calls += 1
        frame = scope.nearest(RunLevel.TURN)
        assert frame is not None
        return CycleOutcome(
            cycle_id=f"cycle_{cycle_index}",
            transfer=RuntimeTransfer.end(frame),
        )


@dataclass
class _RetryTurnPreparation:
    calls: int = 0

    def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        self.calls += 1
        if self.calls == 1:
            frame = request.scope.nearest(RunLevel.TURN)
            assert frame is not None
            raise RuntimeTransferInterrupt(RuntimeTransfer.retry(frame))
        return ()


class _EndProgramPreparation:
    def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        frame = request.scope.nearest(RunLevel.PROGRAM)
        assert frame is not None
        raise RuntimeTransferInterrupt(RuntimeTransfer.end(frame))


@dataclass
class _CompletionRecorder:
    completions: list[TurnCompletion]
    timeline: list[str] | None = None

    def handle(self, completion: TurnCompletion) -> None:
        self.completions.append(completion)
        if self.timeline is not None:
            self.timeline.append("completion")


@dataclass
class _RecordingObservations:
    events: list[ObservationEvent]
    timeline: list[str]

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)
        self.timeline.append(event.name)


@dataclass
class _OutputCycleRunner:
    bus: SignalBus

    def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
    ) -> CycleOutcome:
        frame = scope.nearest(RunLevel.TURN)
        assert frame is not None
        self.bus.emit(
            build_turn_output_signal(
                TurnOutput(text="done", result_id="answer_1"),
                scope=scope,
                source="test",
            )
        )
        return CycleOutcome(
            cycle_id=f"cycle_{cycle_index}",
            transfer=RuntimeTransfer.end(frame),
        )


class _EmptyCycleRunner:
    def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
    ) -> CycleOutcome:
        return CycleOutcome(cycle_id=f"cycle_{cycle_index}")


class _FailingCompletion:
    def handle(self, completion: TurnCompletion) -> None:
        raise RuntimeException(
            reason=RUNTIME_TURN_END,
            message="Session completion failed.",
            payload={"module": "session", "kind": "session.io_failed"},
        )


def test_turn_runner_captures_end_turn_failure_and_aborts_context() -> None:
    context = _EndFailingContext()
    runner = TurnRunner(
        context=cast(ContextEngine, context),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _AnsweredCycleRunner()),
        settings=LoopSettings(max_cycles_per_turn=1),
    )

    outcome = runner.run("hello", business_day=DAY, scope=_program_scope())

    assert outcome.summary is None
    assert context.turn_active is False
    assert context.aborted == 1
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.TURN
    assert outcome.status is TurnOutcomeStatus.FAILED
    assert outcome.failure is not None
    assert outcome.failure.module == "context"


def test_turn_runner_keeps_existing_program_transfer_when_end_turn_fails() -> None:
    context = _EndFailingContext()
    runner = TurnRunner(
        context=cast(ContextEngine, context),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _ProgramEndCycleRunner()),
        settings=LoopSettings(max_cycles_per_turn=1),
    )

    outcome = runner.run("hello", business_day=DAY, scope=_program_scope())

    assert context.turn_active is False
    assert outcome.transfer is not None
    assert outcome.transfer.target.level is RunLevel.PROGRAM
    assert outcome.status is TurnOutcomeStatus.FAILED


def test_turn_completion_pipeline_receives_summary_and_output() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    bus = SignalBus()
    timeline: list[str] = []
    recorder = _CompletionRecorder([], timeline)
    observations = _RecordingObservations([], timeline)
    runner = TurnRunner(
        context=context,
        bus=bus,
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _OutputCycleRunner(bus)),
        settings=LoopSettings(max_cycles_per_turn=1),
        completion_pipeline=TurnCompletionPipeline((recorder,)),
        observations=observations,
    )

    outcome = runner.run("hello", business_day=DAY, scope=_program_scope())

    assert outcome.answered is True
    assert outcome.transfer is None
    assert len(recorder.completions) == 1
    completion = recorder.completions[0]
    assert completion.summary.inputs[0]["text"] == "hello"
    assert completion.summary.trace == ()
    assert completion.output is not None
    assert completion.output.text == "done"
    assert completion.business_day == DAY
    output_event = next(
        event for event in observations.events if event.name == "turn.output"
    )
    assert output_event.payload["text"] == "done"
    assert timeline.index("completion") < timeline.index("turn.output")


def test_turn_preparation_retry_replays_only_preparation() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    preparation = _RetryTurnPreparation()
    cycles = _CountingCycleRunner()
    runner = TurnRunner(
        context=context,
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, cycles),
        settings=LoopSettings(max_cycles_per_turn=1),
        preparation_pipeline=TurnPreparationPipeline((preparation,)),
    )

    outcome = runner.run("hello", business_day=DAY, scope=_program_scope())

    assert preparation.calls == 2
    assert cycles.calls == 1
    assert outcome.summary is not None
    assert outcome.transfer is not None
    assert outcome.transfer.target.level is RunLevel.TURN


def test_turn_completion_failure_reports_actual_failure_not_output_control() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    bus = SignalBus()
    observations = _RecordingObservations([], [])
    runner = TurnRunner(
        context=context,
        bus=bus,
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _OutputCycleRunner(bus)),
        settings=LoopSettings(max_cycles_per_turn=1),
        completion_pipeline=TurnCompletionPipeline((_FailingCompletion(),)),
        observations=observations,
    )

    outcome = runner.run("hello", business_day=DAY, scope=_program_scope())

    assert outcome.status is TurnOutcomeStatus.FAILED
    assert outcome.failure is not None
    assert outcome.failure.module == "session"
    assert outcome.failure.kind == "session.io_failed"
    assert "turn.output" not in {event.name for event in observations.events}
    failed = next(event for event in observations.events if event.name == "turn.failed")
    assert failed.level is ObservationLevel.NORMAL
    assert failed.payload["module"] == "session"


def test_turn_cycle_limit_reports_exhausted_at_normal_level() -> None:
    observations = _RecordingObservations([], [])
    runner = TurnRunner(
        context=ContextEngineBuilder(system_text="sys").build(),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _EmptyCycleRunner()),
        settings=LoopSettings(max_cycles_per_turn=1),
        observations=observations,
    )

    outcome = runner.run("hello", business_day=DAY, scope=_program_scope())

    assert outcome.status is TurnOutcomeStatus.EXHAUSTED
    exhausted = next(
        event for event in observations.events if event.name == "turn.exhausted"
    )
    assert exhausted.level is ObservationLevel.NORMAL


def test_turn_preparation_propagates_program_transfer_without_running_cycle() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    cycles = _CountingCycleRunner()
    runner = TurnRunner(
        context=context,
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, cycles),
        settings=LoopSettings(max_cycles_per_turn=1),
        preparation_pipeline=TurnPreparationPipeline((_EndProgramPreparation(),)),
    )

    outcome = runner.run("hello", business_day=DAY, scope=_program_scope())

    assert cycles.calls == 0
    assert outcome.summary is not None
    assert outcome.transfer is not None
    assert outcome.transfer.target.level is RunLevel.PROGRAM
    assert outcome.status is TurnOutcomeStatus.STOPPED


def _trap() -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
    return RuntimeTrap(registry=registry)


def _program_scope() -> RunScope:
    return RunScope().push(RunLevel.PROGRAM, "program")
