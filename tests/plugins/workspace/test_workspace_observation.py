from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os

import pytest

from tinysoul.runtime import ObservationEvent, ObservationLevel
from tinysoul.runtime.events import EnvironmentEvent, EventReceipt
from tinysoul.infra.filesystem import atomic_write_bytes
from tinysoul.plugins.workspace import (
    WorkspaceBundleWrite,
    WorkspaceTextEdit,
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
    patched = engine.edit_text(
        written.ref,
        (WorkspaceTextEdit("old", "new"),),
    )
    engine.set_description(
        patched.ref,
        "A note.",
    )
    item = engine.trash_resource("workspace:note.md")
    engine.restore_resource(item.ref)

    assert [event.payload["operation"] for event in observations.events] == [
        "write",
        "edit",
        "describe",
        "trash",
        "restore",
    ]
    assert all(event.name == "workspace.changed" for event in observations.events)
    assert all(event.source == "workspace.engine" for event in observations.events)
    assert all(
        event.payload["refs"] == ["workspace:note.md"] for event in observations.events
    )


def test_workspace_bundle_emits_only_one_final_change(tmp_path: Path) -> None:
    observations = _RecordingEmitter()
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path),
        observations=observations,
    ).build()

    result = engine.write_bundle(
        (
            WorkspaceBundleWrite(ref="workspace:a.md", data=b"a"),
            WorkspaceBundleWrite(ref="workspace:b.md", data=b"b"),
        )
    )

    assert len(observations.events) == 1
    event = observations.events[0]
    assert event.payload["operation"] == "bundle"
    assert event.payload["created_refs"] == ["workspace:a.md", "workspace:b.md"]
    assert event.payload["refs"] == ["workspace:a.md", "workspace:b.md"]


async def test_committed_writes_publish_even_when_file_metadata_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations = _RecordingEmitter()
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path),
        observations=observations,
    ).build()
    record = engine.write_text("workspace:note.md", "old")
    observations.events.clear()
    events: list[EnvironmentEvent] = []

    async def publish(event: EnvironmentEvent) -> EventReceipt:
        events.append(event)
        return EventReceipt(len(events), event.event_id, True)

    engine.events.bind(publish)

    def write_with_same_timestamp(path: Path, data: bytes) -> None:
        atomic_write_bytes(path, data)
        os.utime(path, ns=(record.mtime_ns, record.mtime_ns))

    monkeypatch.setattr(
        "tinysoul.plugins.workspace.storage.mutations.atomic_write_bytes",
        write_with_same_timestamp,
    )
    before = engine.snapshot()
    engine.edit_text(record.ref, (WorkspaceTextEdit("old", "new"),))
    engine.write_bundle((WorkspaceBundleWrite(record.ref, b"end", overwrite=True),))
    assert engine.snapshot() == before
    assert (tmp_path / "note.md").read_text() == "end"
    assert [event.payload["operation"] for event in observations.events] == [
        "edit",
        "bundle",
    ]
    assert all(
        event.payload["updated_refs"] == [record.ref] for event in observations.events
    )
    await engine.events.flush()
    assert len(events) == 1
    assert events[0].payload["refs"] == [record.ref]


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
    assert observations.events[0].payload["created_refs"] == ["workspace:external.md"]


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
