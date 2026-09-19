from pathlib import Path

import pytest

from tinysoul.plugins.workspace.config import WorkspaceSettings
from tinysoul.plugins.workspace.errors import WorkspaceInvariantError
from tinysoul.plugins.workspace.links import WorkspaceLink
from tinysoul.plugins.workspace.storage.manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
    WorkspaceTag,
)
from tinysoul.plugins.workspace.storage.reconcile import WorkspaceReconciler


def test_workspace_storage_schema_is_explicit_and_round_trips(tmp_path: Path) -> None:
    store = WorkspaceManifestStore(tmp_path / ".tinysoul" / "workspace_manifest.json")
    record = WorkspaceResourceRecord(
        link="workspace:notes.md",
        relative_path="notes.md",
        kind=WorkspaceResourceKind.TEXT,
        media_type="text/markdown",
        suffix=".md",
        summary="Markdown text, 5 bytes",
        size=5,
        mtime_ns=1,
        tags=(WorkspaceTag.PINNED,),
    )
    manifest = WorkspaceManifest(day="2026-09-19", resources=(record,))
    store.save(manifest)
    assert store.load() == manifest


def test_workspace_storage_rejects_old_cas_fields(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        '{"schema_version":3,"day":"","revision":0,"resources":[]}', encoding="utf-8"
    )
    with pytest.raises(WorkspaceInvariantError):
        WorkspaceManifestStore(path).load()


def test_workspace_storage_reconciles_files_without_content_cas(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.md").write_text("hello", encoding="utf-8")
    settings = WorkspaceSettings(root=root)
    result = WorkspaceReconciler(
        settings=settings,
        manifest_store=WorkspaceManifestStore(settings.manifest_path),
    ).reconcile()
    assert result.complete
    assert result.resources[0].link == str(WorkspaceLink.from_relative_path("notes.md"))
