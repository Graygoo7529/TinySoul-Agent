"""Cross-module context pressure recovery tests."""

from __future__ import annotations

from pathlib import Path

from tinysoul.context import ContextEngineBuilder, ContextSignalBatch
from tinysoul.loop.pressure import (
    ContextPressureRecovery,
    PressureRecoveryStatus,
    _required_chars,
)
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.workspace import (
    WorkspaceEngineBuilder,
    WorkspaceRetention,
    WorkspaceSettings,
)
from tinysoul.workspace.projection import workspace_snapshot_signal


def test_pressure_recovery_trashes_workspace_resource_and_syncs_context(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.write_text(
        "workspace:temporary.txt",
        "temporary",
        retention=WorkspaceRetention.EPHEMERAL,
        owner_turn_id="turn_owner",
    )
    context = ContextEngineBuilder(system_text="system").build()
    turn_id = context.begin_turn("continue")
    scope = _scope(turn_id)
    initial = workspace_snapshot_signal(
        workspace.snapshot(),
        call_id="workspace_initial",
        scope=scope,
        source="test",
    )
    assert context.consume_signal_batch(
        ContextSignalBatch(turn_id=turn_id, signals=(initial,))
    ) == ()
    context.complete_preparation()

    result = ContextPressureRecovery(
        context=context,
        workspace=workspace,
        target_ratio=0.8,
    ).recover(
        payload={"estimated_chars": 101, "max_chars": 100},
        scope=scope,
    )

    assert result.status is PressureRecoveryStatus.RECOVERED
    assert result.trashed_refs
    assert workspace.snapshot().resources == ()
    assert context.working_snapshot()["workspace_resources"] == []


def test_model_pressure_converts_target_token_gap_to_char_reclaim() -> None:
    required = _required_chars(
        {
            "context_window_tokens": 100,
            "estimated_message_tokens": 70,
            "estimated_non_message_tokens": 10,
            "reserved_output_tokens": 10,
            "estimated_message_chars": 700,
        },
        target_ratio=0.5,
    )

    assert required == 400


def test_image_only_pressure_does_not_delete_workspace_files(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace.write_text(
        "workspace:temporary.txt",
        "temporary",
        retention=WorkspaceRetention.EPHEMERAL,
    )
    context = ContextEngineBuilder(system_text="system").build()
    turn_id = context.begin_turn("continue")
    scope = _scope(turn_id)
    context.complete_preparation()

    result = ContextPressureRecovery(
        context=context,
        workspace=workspace,
        target_ratio=0.8,
    ).recover(
        payload={
            "estimated_chars": 50,
            "estimated_image_bytes": 20,
            "max_image_bytes": 10,
        },
        scope=scope,
    )

    assert result.status is PressureRecoveryStatus.NO_PROGRESS
    assert (tmp_path / "temporary.txt").is_file()


def test_pressure_recovery_preserves_active_action_resource_links(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    for name in ("protected.txt", "reclaimable.txt"):
        workspace.write_text(
            f"workspace:{name}",
            name,
            retention=WorkspaceRetention.EPHEMERAL,
        )
    context = ContextEngineBuilder(system_text="system").build()
    turn_id = context.begin_turn("continue")
    scope = _scope(turn_id)
    initial = workspace_snapshot_signal(
        workspace.snapshot(),
        call_id="workspace_initial",
        scope=scope,
        source="test",
    )
    assert context.consume_signal_batch(
        ContextSignalBatch(turn_id=turn_id, signals=(initial,))
    ) == ()
    context.complete_preparation()

    result = ContextPressureRecovery(
        context=context,
        workspace=workspace,
        target_ratio=0.8,
    ).recover(
        payload={
            "estimated_chars": 1000,
            "max_chars": 100,
            "protected_resource_links": ["workspace:protected.txt"],
        },
        scope=scope,
    )

    assert result.status is PressureRecoveryStatus.RECOVERED
    assert {record.link for record in workspace.snapshot().resources} == {
        "workspace:protected.txt"
    }


def _workspace(tmp_path: Path):
    return WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()


def _scope(turn_id: str) -> RunScope:
    return RunScope().push(RunLevel.PROGRAM, "program").push(RunLevel.TURN, turn_id)
