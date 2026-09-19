"""The Workspace owner preserves metadata and reports committed file effects."""

from pathlib import Path
import os

import pytest

from tinysoul.plugins.workspace import (
    WorkspaceContractError,
    WorkspaceEngineBuilder,
    WorkspaceSettings,
    WorkspaceTag,
    WorkspaceTextEdit,
    WorkspaceSearchScope,
    WorkspaceSearchScopeKind,
    WorkspaceBundleWrite,
)
from tinysoul.plugins.workspace.errors import WorkspaceIOError, WorkspaceInvariantError
from tinysoul.plugins.workspace.storage.manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
)
from tinysoul.plugins.workspace.storage.reconcile import WorkspaceReconciler


@pytest.mark.parametrize(
    "edits",
    [
        (WorkspaceTextEdit("missing", "x"),),
        (WorkspaceTextEdit("a", "x"),),
        (WorkspaceTextEdit("beta", "new"), WorkspaceTextEdit("missing", "x")),
        (WorkspaceTextEdit("aa", "x"),),
    ],
)
def test_edit_rejects_missing_ambiguous_and_later_failure_without_partial_write(
    tmp_path: Path,
    edits: tuple[WorkspaceTextEdit, ...],
) -> None:
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    engine.write_text("workspace:a.md", "aaa beta")
    before = engine.snapshot()
    with pytest.raises(WorkspaceContractError):
        engine.edit_text("workspace:a.md", edits)
    assert engine.read_text("workspace:a.md").text == "aaa beta"
    assert engine.snapshot() == before


def test_ordered_edit_append_and_explicit_overwrite(tmp_path: Path) -> None:
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    engine.write_text("workspace:a.md", "first second")
    engine.edit_text(
        "workspace:a.md",
        (
            WorkspaceTextEdit("first", "new"),
            WorkspaceTextEdit("new second", "final"),
        ),
    )
    engine.append_text("workspace:a.md", "\nend")
    assert engine.read_text("workspace:a.md").text == "final\nend"
    with pytest.raises(WorkspaceContractError):
        engine.write_text("workspace:a.md", "replacement")
    engine.write_text("workspace:a.md", "replacement", overwrite=True)
    assert engine.read_text("workspace:a.md").text == "replacement"


def test_directory_move_and_trash_restore_preserve_tags_and_description(
    tmp_path: Path,
) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path / "workspace")
    ).build()
    engine.mkdir("workspace:notes")
    engine.write_text("workspace:notes/a.md", "old")
    engine.tag("workspace:notes", (WorkspaceTag.PINNED,))
    engine.tag("workspace:notes/a.md", (WorkspaceTag.TMP, WorkspaceTag.LIBRARY))
    engine.set_description("workspace:notes/a.md", "A retained description")
    (engine.root / "notes" / "a.md").write_text("external update", encoding="utf-8")
    engine.reconcile()
    engine.move("workspace:notes", "workspace:moved")
    item = engine.trash_resource("workspace:moved")
    assert not (engine.root / "moved").exists()
    assert engine.trash_items() == (item,)
    engine.restore_resource(item.ref)
    assert engine.trash_items() == ()
    assert engine.inspect("workspace:moved").tags == (WorkspaceTag.PINNED,)
    child = engine.inspect("workspace:moved/a.md")
    assert child.tags == (WorkspaceTag.TMP, WorkspaceTag.LIBRARY)
    assert child.description == "A retained description"
    assert engine.read_text(child.link).text == "external update"


def test_move_and_restore_conflicts_preserve_both_contents(tmp_path: Path) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path / "workspace")
    ).build()
    engine.write_text("workspace:a.md", "a")
    engine.write_text("workspace:b.md", "b")
    with pytest.raises(WorkspaceContractError):
        engine.move("workspace:a.md", "workspace:b.md")
    item = engine.trash_resource("workspace:a.md")
    engine.write_text("workspace:a.md", "new")
    with pytest.raises(WorkspaceContractError):
        engine.restore_resource(item.ref)
    assert engine.read_text("workspace:a.md").text == "new"
    assert engine.read_text("workspace:b.md").text == "b"
    assert engine.trash_items() == (item,)


@pytest.mark.parametrize("operation", ["move", "restore"])
def test_relocated_resource_never_commits_an_index_without_its_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path / "workspace")
    ).build()
    engine.write_text("workspace:a.md", "a")
    engine.tag("workspace:a.md", (WorkspaceTag.PINNED,))
    engine.set_description("workspace:a.md", "Keep this description")
    trash = engine.trash_resource("workspace:a.md") if operation == "restore" else None
    persisted: list[WorkspaceManifest] = []
    save = WorkspaceManifestStore.save

    def observe(self: WorkspaceManifestStore, manifest: WorkspaceManifest) -> None:
        save(self, manifest)
        persisted.append(self.load())

    monkeypatch.setattr(WorkspaceManifestStore, "save", observe)
    if trash is not None:
        result = engine.restore_resource(trash.ref)
    else:
        result = engine.move("workspace:a.md", "workspace:b.md")
    assert persisted
    for manifest in persisted:
        record = next(item for item in manifest.resources if item.link == result.link)
        assert record.tags == (WorkspaceTag.PINNED,)
        assert record.description == "Keep this description"


def test_index_failure_reports_committed_files_without_claiming_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()

    def fail_save(self: WorkspaceManifestStore, manifest) -> None:
        raise WorkspaceIOError("private storage failure")

    monkeypatch.setattr(WorkspaceManifestStore, "save", fail_save)
    with pytest.raises(WorkspaceIOError) as raised:
        engine.write_text("workspace:a.md", "committed")
    assert raised.value.committed_links == ("workspace:a.md",)
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "committed"
    assert "private" not in str(raised.value)


@pytest.mark.parametrize("operation", ["move", "restore"])
@pytest.mark.parametrize("failure_at", ["metadata", "move", "index"])
def test_relocation_failure_preserves_metadata_across_owner_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    failure_at: str,
) -> None:
    settings = WorkspaceSettings(root=tmp_path / "workspace")
    engine = WorkspaceEngineBuilder(settings).build()
    engine.mkdir("workspace:notes")
    engine.write_text("workspace:notes/a.md", "kept")
    engine.tag("workspace:notes", (WorkspaceTag.PINNED,))
    engine.set_description("workspace:notes/a.md", "retained description")
    trash = engine.trash_resource("workspace:notes") if operation == "restore" else None
    destination = "workspace:notes" if trash else "workspace:moved"
    source = (
        settings.trash_root / trash.trash_id / "content"
        if trash
        else engine.root / "notes"
    )

    def fail(*args, **kwargs):
        raise WorkspaceIOError("injected private failure")

    replace = os.replace

    def fail_move(src, dst):
        if src == source:
            raise OSError("injected move failure")
        return replace(src, dst)

    with monkeypatch.context() as patch:
        if failure_at == "metadata":
            patch.setattr(WorkspaceManifestStore, "save", fail)
        elif failure_at == "move":
            patch.setattr(os, "replace", fail_move)
        else:
            patch.setattr(WorkspaceReconciler, "reconcile", fail)
        with pytest.raises(WorkspaceIOError) as raised:
            if trash:
                engine.restore_resource(trash.ref)
            else:
                engine.move("workspace:notes", destination)
        expected = ()
        if failure_at == "index":
            expected = (destination,) if trash else ("workspace:notes", destination)
        assert raised.value.committed_links == expected

    reopened = WorkspaceEngineBuilder(settings).build()
    assert reopened.reconcile().complete
    if failure_at != "index" and trash:
        assert reopened.trash_items() == (trash,)
        reopened.restore_resource(trash.ref)
    location = destination if failure_at == "index" else "workspace:notes"
    assert reopened.inspect(location).tags == (WorkspaceTag.PINNED,)
    assert reopened.inspect(location + "/a.md").description == "retained description"
    assert reopened.read_text(location + "/a.md").text == "kept"
    assert {record.link for record in reopened.snapshot().resources} == {
        location,
        location + "/a.md",
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive paths")
@pytest.mark.parametrize("conflict", ["writes", "write_delete", "deletes"])
def test_bundle_rejects_case_aliases_before_any_write(
    tmp_path: Path,
    conflict: str,
) -> None:
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    if conflict != "writes":
        engine.write_text("workspace:a.md", "original")
    if conflict == "writes":
        writes = (
            WorkspaceBundleWrite("workspace:a.md", b"first"),
            WorkspaceBundleWrite("workspace:A.md", b"second"),
        )
        deletes = ()
    else:
        target = "workspace:A.md" if conflict == "write_delete" else "workspace:b.md"
        writes = (WorkspaceBundleWrite(target, b"changed", overwrite=True),)
        deletes = (
            ("workspace:a.md",) if conflict == "write_delete"
            else ("workspace:a.md", "workspace:A.md")
        )
    before = engine.snapshot()
    with pytest.raises(WorkspaceContractError):
        engine.write_bundle(writes, delete_links=deletes)
    assert engine.snapshot() == before
    assert engine.trash_items() == ()
    if conflict == "writes":
        assert not (tmp_path / "a.md").exists()
    else:
        assert engine.read_text("workspace:a.md").text == "original"
        assert not (tmp_path / "b.md").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive paths")
def test_overwrite_alias_returns_disk_identity_and_preserves_metadata(
    tmp_path: Path,
) -> None:
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    original = engine.write_text("workspace:a.md", "first")
    engine.tag(original.link, (WorkspaceTag.PINNED,))
    engine.set_description(original.link, "retained")
    record = engine.write_text("workspace:A.md", "replacement", overwrite=True)
    assert record.link == original.link
    assert record.tags == (WorkspaceTag.PINNED,)
    assert record.description == "retained"
    assert engine.read_text(original.link).text == "replacement"


def test_bundle_failure_preserves_inner_delete_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    engine.write_text("workspace:a.md", "recoverable")

    def fail_save(self: WorkspaceManifestStore, manifest: WorkspaceManifest) -> None:
        raise WorkspaceIOError("private index failure")

    with monkeypatch.context() as patch:
        patch.setattr(WorkspaceManifestStore, "save", fail_save)
        with pytest.raises(WorkspaceIOError) as raised:
            engine.write_bundle(
                (WorkspaceBundleWrite("workspace:b.md", b"created"),),
                delete_links=("workspace:a.md",),
            )
    assert raised.value.committed_links == ("workspace:b.md", "workspace:a.md")
    assert not (tmp_path / "a.md").exists()
    assert engine.read_text("workspace:b.md").text == "created"
    assert len(engine.trash_items()) == 1
    assert "private" not in str(raised.value)


def test_incomplete_discovery_keeps_existing_metadata(tmp_path: Path) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, max_files=1)
    ).build()
    engine.write_text("workspace:a.md", "a")
    engine.tag("workspace:a.md", (WorkspaceTag.PINNED,))
    before = engine.snapshot()
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    assert not engine.reconcile().complete
    assert engine.snapshot() == before


def test_regex_search_has_explicit_scope_and_rejects_invalid_pattern(
    tmp_path: Path,
) -> None:
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    engine.write_text("workspace:a.md", "alpha 12\nbeta 34\n")
    scope = WorkspaceSearchScope(WorkspaceSearchScopeKind.FILE, "workspace:a.md")
    result = engine.search(query=r"alpha\s+\d+", scope=scope, use_regex=True)
    assert result.fragments and "alpha 12" in result.fragments[0].text
    with pytest.raises(WorkspaceContractError):
        engine.search(query="[", scope=scope, use_regex=True)


def test_regex_timeout_reports_incomplete_coverage_and_owner_remains_usable(
    tmp_path: Path,
) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, max_write_chars=120000)
    ).build()
    engine.write_text("workspace:long.txt", "a" * 100000 + "!")
    scope = WorkspaceSearchScope(WorkspaceSearchScopeKind.FILE, "workspace:long.txt")
    result = engine.search(query=r"(a+)+$", scope=scope, use_regex=True)
    assert not result.coverage.complete
    assert result.coverage.reason == "regex_timeout"
    assert not result.fragments
    assert engine.search(query="!", scope=scope).fragments


@pytest.mark.parametrize("document", [None, "not json", '{"trashed_at": NaN}', "{}"])
def test_trash_corruption_is_owner_failure_and_keeps_recoverable_content(
    tmp_path: Path,
    document: str | None,
) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path / "workspace")
    ).build()
    engine.write_text("workspace:a.md", "recoverable")
    item = engine.trash_resource("workspace:a.md")
    entry = engine.settings.trash_root / item.trash_id
    metadata = entry / "metadata.json"
    if document is None:
        metadata.unlink()
    else:
        metadata.write_text(document, encoding="utf-8")
    with pytest.raises(WorkspaceInvariantError):
        engine.restore_resource(item.ref)
    assert (entry / "content").read_text(encoding="utf-8") == "recoverable"
    assert not (engine.root / "a.md").exists()
