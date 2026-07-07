from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from tinysoul.loop import ProgramInputEvent, ProgramRunner, TurnOutcome, TurnRunner
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

    def run(self, user_input: str, *, scope: RunScope) -> TurnOutcome:
        self.inputs.append(user_input)
        return TurnOutcome(summary=None, answered=True)


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
    )

    runner.submit_event(
        ProgramInputEvent.exit_program(
            text="bye",
            source="test",
            metadata={"reason": "unit"},
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
    }


def _trap(handler: _ProgramEndHandler) -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_PROGRAM_END, handler)
    return RuntimeTrap(registry=registry)
