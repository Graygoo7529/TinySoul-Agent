from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from tinysoul.context import ContextEngine, ContextEngineBuilder
from tinysoul.context.errors import ContextContractError
from tinysoul.loop import LoopSettings
from tinysoul.loop import (
    TurnCompletion,
    TurnCompletionPipeline,
    TurnOutput,
    build_turn_output_signal,
)
from tinysoul.loop.cycle import CycleOutcome, CycleRunner
from tinysoul.loop.trap_handlers import EndFrameTrapHandler
from tinysoul.loop.turn import TurnRunner
from tinysoul.runtime import (
    RUNTIME_TURN_END,
    RunLevel,
    RunScope,
    RuntimeTransfer,
    RuntimeTransferAction,
    RuntimeTrap,
    SignalBus,
    TrapHandlerRegistry,
)


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
class _CompletionRecorder:
    completions: list[TurnCompletion]

    def handle(self, completion: TurnCompletion) -> None:
        self.completions.append(completion)


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


def test_turn_runner_captures_end_turn_failure_and_aborts_context() -> None:
    context = _EndFailingContext()
    runner = TurnRunner(
        context=cast(ContextEngine, context),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _AnsweredCycleRunner()),
        settings=LoopSettings(max_cycles_per_turn=1),
    )

    outcome = runner.run("hello", scope=_program_scope())

    assert outcome.summary is None
    assert context.turn_active is False
    assert context.aborted == 1
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.TURN


def test_turn_runner_keeps_existing_program_transfer_when_end_turn_fails() -> None:
    context = _EndFailingContext()
    runner = TurnRunner(
        context=cast(ContextEngine, context),
        bus=SignalBus(),
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _ProgramEndCycleRunner()),
        settings=LoopSettings(max_cycles_per_turn=1),
    )

    outcome = runner.run("hello", scope=_program_scope())

    assert context.turn_active is False
    assert outcome.transfer is not None
    assert outcome.transfer.target.level is RunLevel.PROGRAM


def test_turn_completion_pipeline_receives_summary_and_output() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    bus = SignalBus()
    recorder = _CompletionRecorder([])
    runner = TurnRunner(
        context=context,
        bus=bus,
        trap=_trap(),
        cycle_runner=cast(CycleRunner, _OutputCycleRunner(bus)),
        settings=LoopSettings(max_cycles_per_turn=1),
        completion_pipeline=TurnCompletionPipeline((recorder,)),
    )

    outcome = runner.run("hello", scope=_program_scope())

    assert outcome.answered is True
    assert outcome.transfer is None
    assert len(recorder.completions) == 1
    completion = recorder.completions[0]
    assert completion.summary.inputs[0]["text"] == "hello"
    assert completion.summary.trace == ()
    assert completion.output is not None
    assert completion.output.text == "done"


def _trap() -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_TURN_END, EndFrameTrapHandler(RunLevel.TURN))
    return RuntimeTrap(registry=registry)


def _program_scope() -> RunScope:
    return RunScope().push(RunLevel.PROGRAM, "program")
