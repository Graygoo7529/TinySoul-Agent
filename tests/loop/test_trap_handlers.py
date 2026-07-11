from __future__ import annotations

from pathlib import Path

from tinysoul.context import ContextEngineBuilder, build_trace_phase_note_signal
from tinysoul.loop.pressure import ContextPressureRecovery
from tinysoul.loop.trap_handlers import ContextPressureTrapHandler
from tinysoul.runtime import (
    CONTEXT_COMPRESSION_REQUIRED,
    CyclePhase,
    RunLevel,
    RunScope,
    RuntimeTransferAction,
    SignalBus,
    TrapSnap,
)
from tinysoul.workspace import WorkspaceEngineBuilder, WorkspaceSettings


def test_context_pressure_trap_retries_current_phase_when_trace_changes(
    tmp_path: Path,
) -> None:
    context = (
        ContextEngineBuilder(system_text="sys")
        .with_trace_heap(
            chunk_max_chars=12000,
            branch_factor=4,
            min_hot_entries=0,
        )
        .build()
    )
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
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
                    {"index": index, "detail": "x" * 500},
                scope=scope,
                source="test",
                cycle_id="cycle_1",
                phase=CyclePhase.PHASE2,
            )
        )
    context.consume_signals(bus)

    result = ContextPressureTrapHandler(
        ContextPressureRecovery(
            context=context,
            workspace=workspace,
            target_ratio=0.8,
        )
    ).handle(
        TrapSnap(
            reason=CONTEXT_COMPRESSION_REQUIRED,
            message="budget exceeded",
            scope=scope,
            payload={"estimated_chars": 100, "max_chars": 50},
        )
    )

    assert result.transfer.action is RuntimeTransferAction.RETRY
    assert result.transfer.target == scope.current()
