from __future__ import annotations

from tinysoul.context import ContextEngineBuilder, build_trace_phase_note_signal
from tinysoul.loop.trap_handlers import ContextCompressionTrapHandler
from tinysoul.runtime import (
    CONTEXT_COMPRESSION_REQUIRED,
    CyclePhase,
    RunLevel,
    RunScope,
    RuntimeTransferAction,
    SignalBus,
    TrapSnap,
)


def test_context_compression_trap_retries_current_phase_when_trace_changes() -> None:
    context = ContextEngineBuilder(system_text="sys").with_keep_recent(1).build()
    turn_id = context.begin_turn("compress me")
    bus = SignalBus()
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE2.value)
    )
    for index in range(3):
        bus.emit(
            build_trace_phase_note_signal(
                {"index": index},
                scope=scope,
                source="test",
                cycle_id="cycle_1",
                phase=CyclePhase.PHASE2,
            )
        )
    context.consume_signals(bus)

    result = ContextCompressionTrapHandler(context).handle(
        TrapSnap(
            reason=CONTEXT_COMPRESSION_REQUIRED,
            message="budget exceeded",
            scope=scope,
        )
    )

    assert result.transfer.action is RuntimeTransferAction.RETRY
    assert result.transfer.target == scope.current()
