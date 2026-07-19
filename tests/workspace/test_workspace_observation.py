from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tinysoul.runtime import ObservationEvent, ObservationLevel
from tinysoul.workspace import (
    WorkspaceBundleWrite,
    WorkspaceContractError,
    WorkspaceEngineBuilder,
    WorkspaceSettings,
)


@dataclass
class _RecordingEmitter:
    events: list[ObservationEvent] = field(default_factory=list)

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)


def test_workspace_engine_emits_committed_mutations_from_one_owner(
    tmp_path: Path,
) -> None:
    observations = _RecordingEmitter()
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path),
        observations=observations,
    ).build()

    written = engine.write_text("workspace:note.md", "old")
    patched = engine.patch_text(
        written.link,
        old_text="old",
        new_text="new",
        expected_digest=written.digest,
    )
    engine.set_description(
        patched.link,
        "A note.",
        expected_digest=patched.digest,
    )
    item = engine.trash_resource("workspace:note.md", reason="test")
    engine.restore_resource(item.ref)

    assert [event.payload["operation"] for event in observations.events] == [
        "write",
        "patch",
        "describe",
        "trash",
        "restore",
    ]
    assert all(event.name == "workspace.changed" for event in observations.events)
    assert all(event.source == "workspace.engine" for event in observations.events)
    assert all(event.payload["links"] == ["workspace:note.md"] for event in observations.events)
    assert observations.events[-1].payload["revision"] == engine.load_manifest().revision


def test_workspace_bundle_emits_only_one_final_change(tmp_path: Path) -> None:
    observations = _RecordingEmitter()
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path),
        observations=observations,
    ).build()

    result = engine.write_bundle(
        (
            WorkspaceBundleWrite(link="workspace:a.md", data=b"a"),
            WorkspaceBundleWrite(link="workspace:b.md", data=b"b"),
        )
    )

    assert len(observations.events) == 1
    event = observations.events[0]
    assert event.payload["operation"] == "bundle"
    assert event.payload["created_links"] == ["workspace:a.md", "workspace:b.md"]
    assert event.payload["links"] == ["workspace:a.md", "workspace:b.md"]
    assert event.payload["revision"] == result.manifest.revision


def test_workspace_reconcile_emits_external_disk_change(tmp_path: Path) -> None:
    observations = _RecordingEmitter()
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path),
        observations=observations,
    ).build()
    (tmp_path / "external.md").write_text("external", encoding="utf-8")

    result = engine.reconcile()

    assert result.complete is True
    assert len(observations.events) == 1
    assert observations.events[0].payload["operation"] == "reconcile"
    assert observations.events[0].payload["created_links"] == [
        "workspace:external.md"
    ]


def test_workspace_failed_mutation_does_not_emit_change(tmp_path: Path) -> None:
    observations = _RecordingEmitter()
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path),
        observations=observations,
    ).build()
    engine.write_text("workspace:note.md", "first")
    observations.events.clear()

    with pytest.raises(WorkspaceContractError):
        engine.write_text("workspace:note.md", "second")

    assert observations.events == []
