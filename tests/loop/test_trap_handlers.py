from __future__ import annotations

from pathlib import Path

from tinysoul.context import (
    ContextEngineBuilder,
    ContextSignalBatch,
    build_trace_phase_note_signal,
)
from tinysoul.loop.user.pressure import UserContextPressureRecovery
from tinysoul.loop.trap_handlers import (
    ContextPressureTrapHandler,
)
from tinysoul.loop.user.trap_handlers import WorkspaceTrashRestoreTrapHandler
from tinysoul.runtime import (
    CONTEXT_COMPRESSION_REQUIRED,
    CyclePhase,
    RunLevel,
    RunScope,
    RuntimeTransferAction,
    SignalBus,
    TrapSnap,
    WORKSPACE_TRASH_RESTORE_REQUIRED,
)
from tinysoul.workspace import WorkspaceEngineBuilder, WorkspaceSettings
from tinysoul.workspace.projection import workspace_snapshot_signal


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
        UserContextPressureRecovery(
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


def test_workspace_trash_restore_trap_syncs_context_and_retries_module(
    tmp_path: Path,
) -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    workspace.write_text("workspace:draft.md", "draft")
    turn_id = context.begin_turn("continue")
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
        .push(RunLevel.MODULE, "action.execute")
    )
    initial = workspace_snapshot_signal(
        workspace.snapshot(),
        call_id="initial",
        scope=scope,
        source="test",
    )
    assert context.consume_signal_batch(
        ContextSignalBatch(turn_id=turn_id, signals=(initial,))
    ) == ()
    context.complete_preparation()
    trash = workspace.trash_resource("workspace:draft.md", reason="pressure")
    removed = workspace_snapshot_signal(
        workspace.snapshot(),
        call_id="removed",
        scope=scope,
        source="test",
    )
    assert context.consume_signal_batch(
        ContextSignalBatch(turn_id=turn_id, signals=(removed,))
    ) == ()

    result = WorkspaceTrashRestoreTrapHandler(
        workspace=workspace,
        context=context,
    ).handle(
        TrapSnap(
            reason=WORKSPACE_TRASH_RESTORE_REQUIRED,
            message="restore",
            scope=scope,
            payload={
                "link": "workspace:draft.md",
                "trash_ref": trash.ref,
            },
        )
    )

    assert result.transfer.action is RuntimeTransferAction.RETRY
    assert result.transfer.target == scope.current()
    assert (tmp_path / "draft.md").read_text(encoding="utf-8") == "draft"
    resources = context.working_snapshot()["workspace_resources"]
    assert isinstance(resources, list)
    resource = resources[0]
    assert isinstance(resource, dict)
    assert resource["link"] == "workspace:draft.md"
