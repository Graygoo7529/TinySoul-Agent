from __future__ import annotations

from datetime import date as CalendarDate

from datetime import date
from tinysoul.plugins.workspace.projection import workspace_segment_registration

from pathlib import Path

from tinysoul.kernel.context import (
    ContextEngineBuilder,
    ContextSignalBatch,
    build_input_append_signal,
    build_trace_phase_note_signal,
)
from tinysoul.agent.user.pressure import UserContextPressureRecovery
from tinysoul.kernel.loop.context_signals import ContextSignalConsumer
from tinysoul.kernel.loop.trap_handlers import (
    ContextPressureTrapHandler,
)
from tinysoul.kernel.context.failures import CONTEXT_COMPRESSION_REQUIRED
from tinysoul.runtime import (
    CyclePhase,
    RunLevel,
    RunScope,
    RuntimeTransferAction,
    RuntimeModuleRunner,
    RuntimeTrap,
    RuntimeException,
    TrapHandlerRegistry,
    SignalBus,
    TrapSnap,
)
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings
from tinysoul.plugins.workspace.projection import workspace_snapshot_signal


async def test_context_pressure_trap_retries_current_phase_when_trace_changes(
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
    await context.open_segments(CalendarDate(2026, 7, 12))
    bus = SignalBus()
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
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
    await context.consume_signals(bus)

    result = ContextPressureTrapHandler(
        UserContextPressureRecovery(
            context=context,
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
