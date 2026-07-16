from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Barrier
from typing import cast

import pytest

from tinysoul.action.core.call import ActionCall, ActionExecution, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.action.core.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.context import (
    ContextEngineBuilder,
    PromptReferenceError,
    SIGNAL_WORKSPACE_SYNC,
)
from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import ImagePart, TextPart, UserMessage
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.loop import BusinessDay, TurnPreparationRequest
from tinysoul.runtime import RunLevel, RunScope, SignalBus
from tinysoul.runtime.bridge import RuntimeWorkspaceBridge
from tinysoul.workspace import (
    WorkspaceContractError,
    WorkspaceBundleWrite,
    WorkspaceDiscoverySkipKind,
    WorkspaceEngineBuilder,
    WorkspaceLink,
    WorkspaceManifest,
    WorkspacePromptInput,
    WorkspacePromptReferenceResolver,
    WorkspaceReconciliationError,
    WorkspaceReconcileStatus,
    WorkspaceRetention,
    WorkspaceResourceKind,
    WorkspaceSettings,
    WorkspaceTextSlice,
    WorkspaceTrashRestoreRequired,
)


def test_workspace_document_read_is_bounded_and_digest_checked(local_tmp: Path) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=(local_tmp / "workspace").resolve())
    ).build()
    source = engine.root / "report.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-test")
    engine.reconcile()

    document = engine.read_document("workspace:report.pdf", max_bytes=100)

    assert document.data == b"%PDF-test"
    assert document.suffix == ".pdf"
    with pytest.raises(WorkspaceContractError, match="exceeds the read limit"):
        engine.read_document("workspace:report.pdf", max_bytes=2)


def test_workspace_bundle_commits_one_revision_and_rolls_back_on_limit(
    local_tmp: Path,
) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=(local_tmp / "workspace").resolve(), max_files=3)
    ).build()
    before = engine.snapshot().revision

    result = engine.write_bundle(
        (
            WorkspaceBundleWrite("workspace:out/report.md", b"report"),
            WorkspaceBundleWrite(
                "workspace:out/report.assets/image.png", b"\x89PNG\r\n\x1a\n"
            ),
        )
    )

    assert result.manifest.revision == before + 1
    assert len(result.records) == 2

    limited = WorkspaceEngineBuilder(
        WorkspaceSettings(root=(local_tmp / "limited").resolve(), max_files=1)
    ).build()
    with pytest.raises(WorkspaceReconciliationError):
        limited.write_bundle(
            (
                WorkspaceBundleWrite("workspace:a.md", b"a"),
                WorkspaceBundleWrite("workspace:b.md", b"b"),
            )
        )
    assert not (limited.root / "a.md").exists()
    assert not (limited.root / "b.md").exists()
from tinysoul.workspace.engine import WorkspaceEngine
from tinysoul.workspace.errors import WorkspaceIOError
from tinysoul.workspace.manifest import WorkspaceManifestStore
from tinysoul.workspace.projection import WorkspaceTurnPreparationHandler
from tinysoul.workspace.pressure import WorkspacePressureReclaimer
from tinysoul.workspace.actions import (
    WorkspaceDeleteExecutor,
    WorkspaceDescribeExecutor,
    WorkspacePatchExecutor,
    WorkspaceRewriteExecutor,
    WorkspaceScanExecutor,
    WorkspaceWriteExecutor,
)


DAY = BusinessDay.parse("2026-07-12")


class FakeLLMRunner:
    def __init__(
        self,
        answer: JsonObject | None = None,
        on_run: Callable[[], None] | None = None,
    ) -> None:
        self.calls: list[TaskCall] = []
        self.answer = answer or {"text": "new text"}
        self.on_run = on_run

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        if self.on_run is not None:
            self.on_run()
        return TaskResult.success(
            raw_response=RawResponse(
                answer_text="{}",
                model_id="fake",
                provider_id="fake",
            ),
            answer=JsonAnswer(self.answer),
            tool_calls=(),
        )


class _FailingManifestStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.manifest = WorkspaceManifest()

    def load(self) -> WorkspaceManifest:
        return self.manifest

    def save(self, manifest: WorkspaceManifest) -> None:
        raise WorkspaceIOError("manifest unavailable")


def test_workspace_link_rejects_unsafe_paths() -> None:
    assert str(WorkspaceLink.parse("workspace:docs/a.md")) == "workspace:docs/a.md"
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("file:docs/a.md")
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("workspace:../secret.md")
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("workspace:C:/secret.md")


def test_workspace_scan_updates_manifest_and_emits_workspace_snapshot(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored").write_text("x", encoding="utf-8")
    manifest_path = tmp_path / ".tinysoul" / "workspace_manifest.json"
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, manifest_path=manifest_path)
    ).build()
    bus = SignalBus()
    execution = _execution("workspace.scan", {})

    result = WorkspaceScanExecutor(engine, bus).execute(
        execution,
        ActionExecutionContext(signal_bus=bus),
    )

    assert result.payload is not None
    payload = result.payload
    assert payload["count"] == 1
    assert payload["resources"] == [
        {"link": "workspace:docs/a.md", "summary": "Markdown text, 5 bytes"}
    ]
    assert payload["skipped_count"] == 0
    assert payload["skip_counts"] == {}
    assert payload["limit_reached"] is False
    assert manifest_path.is_file()
    snapshot = _workspace_snapshot_payload(bus)
    assert snapshot["revision"] == engine.load_manifest().revision
    resources = snapshot["resources"]
    assert isinstance(resources, list)
    first_resource = resources[0]
    assert isinstance(first_resource, dict)
    assert first_resource["link"] == "workspace:docs/a.md"


def test_workspace_scan_manifest_file_does_not_hide_root(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    manifest_path = tmp_path / "workspace_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, manifest_path=manifest_path)
    ).build()

    result = engine.reconcile()

    assert [resource.link for resource in result.resources] == ["workspace:a.md"]
    assert result.skipped_count == 1
    assert result.skipped[0].kind is WorkspaceDiscoverySkipKind.INTERNAL


def test_workspace_scan_reports_limit_reached(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "b.md").write_text("b", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
            max_files=1,
        )
    ).build()

    result = engine.reconcile()

    assert [resource.link for resource in result.resources] == ["workspace:a.md"]
    assert result.limit_reached is True
    assert result.status is WorkspaceReconcileStatus.INCOMPLETE
    assert engine.load_manifest().resources == ()


def test_workspace_reconcile_keeps_revision_when_disk_is_unchanged(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    first = engine.reconcile()
    second = engine.reconcile()

    assert first.changed is True
    assert second.changed is False
    assert second.manifest.revision == first.manifest.revision


def test_workspace_reconcile_preserves_manifest_when_candidate_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "a.md"
    target.write_text("hello", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    original_stat = Path.stat
    target_stat_calls = 0

    def changing_stat(
        path: Path,
        *,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        nonlocal target_stat_calls
        stat = original_stat(path, follow_symlinks=follow_symlinks)
        if path == target:
            target_stat_calls += 1
            if target_stat_calls >= 2:
                values = list(stat)
                values[6] += 1
                return os.stat_result(values)
        return stat

    monkeypatch.setattr(Path, "stat", changing_stat)

    result = engine.reconcile()

    assert result.status is WorkspaceReconcileStatus.INCOMPLETE
    assert result.skipped[-1].kind is WorkspaceDiscoverySkipKind.CONCURRENT_CHANGE
    assert engine.load_manifest().resources == ()


def test_workspace_classifies_prompt_access_kinds(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "report.pdf").write_bytes(b"%PDF")
    (tmp_path / "archive.bin").write_bytes(b"\x00\x01")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    records = {record.link: record for record in engine.reconcile().manifest.resources}

    assert records["workspace:a.md"].kind is WorkspaceResourceKind.TEXT
    assert records["workspace:image.png"].kind is WorkspaceResourceKind.IMAGE
    assert records["workspace:report.pdf"].kind is WorkspaceResourceKind.DOCUMENT
    assert records["workspace:archive.bin"].kind is WorkspaceResourceKind.BINARY


def test_workspace_prompt_resolver_loads_images_and_rejects_documents(
    tmp_path: Path,
) -> None:
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "report.pdf").write_bytes(b"%PDF")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    resolver = WorkspacePromptReferenceResolver(engine)

    blocks = resolver.resolve_reference("workspace:image.png")

    assert any(isinstance(part, ImagePart) for part in blocks[0].message.parts)
    with pytest.raises(PromptReferenceError) as raised:
        resolver.resolve_reference("workspace:report.pdf")
    assert raised.value.reason == "conversion_required"


def test_workspace_prompt_resolver_rejects_image_with_invalid_signature(
    tmp_path: Path,
) -> None:
    (tmp_path / "image.png").write_bytes(b"not a png")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    resolver = WorkspacePromptReferenceResolver(engine)

    with pytest.raises(PromptReferenceError) as raised:
        resolver.resolve_reference("workspace:image.png")

    assert raised.value.reason == "invalid_image_resource"


def test_workspace_description_is_cleared_when_content_changes(tmp_path: Path) -> None:
    path = tmp_path / "a.md"
    path.write_text("hello", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    record = engine.reconcile().manifest.resources[0]
    described = engine.set_description(
        record.link,
        "A greeting document.",
        expected_digest=record.digest,
    )

    engine.write_text(
        record.link,
        "changed",
        overwrite=True,
        expected_digest=described.digest,
    )

    current = engine.load_manifest().resources[0]
    assert current.description == ""
    assert current.described_digest == ""


def test_workspace_turn_preparation_projects_manifest_into_context(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    workspace = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    workspace.initialize_day(DAY)
    context = ContextEngineBuilder(system_text="system").build()
    turn_id = context.begin_turn("hello")
    scope = RunScope().push(RunLevel.PROGRAM, "program").push(RunLevel.TURN, turn_id)
    bus = SignalBus()
    handler = WorkspaceTurnPreparationHandler(
        workspace,
        runtime_bridge=RuntimeWorkspaceBridge(),
    )

    for signal in handler.prepare(
        TurnPreparationRequest(
            turn_id=turn_id,
            user_input="hello",
            business_day=DAY,
            scope=scope,
        )
    ):
        bus.emit(signal)
    assert context.consume_signals(bus) == ()

    working = context.working_snapshot()
    assert working["workspace_revision"] == workspace.load_manifest().revision
    assert working["workspace_resources"] == [
        {"link": "workspace:a.md", "summary": "Markdown text, 5 bytes"}
    ]


def test_workspace_read_text_returns_bounded_text(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("abcdef", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    result = engine.read_text("workspace:a.md", max_chars=3)

    assert result.link == "workspace:a.md"
    assert result.text == "abc"
    assert result.truncated is True
    assert engine.load_manifest().resources == ()


def test_workspace_read_text_rejects_non_positive_limit(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("abcdef", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    with pytest.raises(WorkspaceContractError, match="positive"):
        engine.read_text("workspace:a.md", max_chars=0)


def test_workspace_prepare_task_input_renders_bounded_resources(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("abcdef", encoding="utf-8")
    (tmp_path / "b.md").write_text("xyz", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    task_input = engine.prepare_task_input(
        ("workspace:a.md", "workspace:b.md"),
        max_chars_per_resource=3,
    )

    assert isinstance(task_input, WorkspacePromptInput)
    assert len(task_input.slices) == 2
    assert isinstance(task_input.slices[0], WorkspaceTextSlice)
    assert task_input.slices[0].range_label == "prefix:3"
    assert task_input.truncated is True
    rendered = task_input.render()
    assert "## workspace:a.md" in rendered
    assert "range: prefix:3" in rendered
    assert "abc" in rendered
    assert "truncated: true" in rendered
    assert "## workspace:b.md" in rendered


def test_workspace_prompt_reference_resolver_returns_prefix_block(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("abcdef", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
            max_read_chars=3,
        )
    ).build()
    resolver = WorkspacePromptReferenceResolver(engine)

    blocks = resolver.resolve_reference("workspace:a.md")

    assert len(blocks) == 1
    assert blocks[0].label == "task_prompt:input:workspace:reference:workspace:a.md:prefix:3"
    text = _message_text(blocks[0].message)
    assert "# Workspace Reference" in text
    assert "link: workspace:a.md" in text
    assert "abc" in text
    assert "truncated: true" in text


def test_workspace_prompt_reference_resolver_returns_target_block(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("abcdef", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
            max_read_chars=3,
        )
    ).build()
    resolver = WorkspacePromptReferenceResolver(engine)

    blocks = resolver.resolve_target("workspace:a.md")

    assert len(blocks) == 1
    assert blocks[0].label == "task_prompt:input:workspace:target:workspace:a.md:prefix:3"
    text = _message_text(blocks[0].message)
    assert "# Workspace Target" in text
    assert "link: workspace:a.md" in text
    assert "abc" in text
    assert "truncated: true" in text


def test_workspace_read_text_slice_returns_line_range(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    result = engine.read_text_slice(
        "workspace:a.md",
        start_line=2,
        max_lines=2,
        max_chars=100,
    )

    assert result.link == "workspace:a.md"
    assert result.range_label == "lines:2-3"
    assert result.text == "two\nthree\n"
    assert result.truncated is True


def test_workspace_read_text_slice_applies_char_limit(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("abcdef\n", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    result = engine.read_text_slice(
        "workspace:a.md",
        start_line=1,
        max_chars=3,
    )

    assert result.range_label == "lines:1-1"
    assert result.text == "abc"
    assert result.truncated is True


def test_workspace_read_text_slice_rejects_invalid_bounds(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("abcdef", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    with pytest.raises(WorkspaceContractError, match="start_line"):
        engine.read_text_slice("workspace:a.md", start_line=0)
    with pytest.raises(WorkspaceContractError, match="max_lines"):
        engine.read_text_slice("workspace:a.md", max_lines=0)
    with pytest.raises(WorkspaceContractError, match="limit"):
        engine.read_text_slice("workspace:a.md", max_chars=0)


def test_workspace_write_text_creates_resource_and_manifest(tmp_path: Path) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    record = engine.write_text("workspace:docs/a.md", "hello")

    assert (tmp_path / "docs" / "a.md").read_text(encoding="utf-8") == "hello"
    assert record.link == "workspace:docs/a.md"
    assert record.size == 5
    assert engine.load_manifest().resources[0].link == "workspace:docs/a.md"


def test_workspace_write_text_rejects_existing_without_overwrite(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("old", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    with pytest.raises(WorkspaceContractError, match="already exists"):
        engine.write_text("workspace:a.md", "new")


def test_workspace_write_rolls_back_when_manifest_reconciliation_fails(
    tmp_path: Path,
) -> None:
    target = tmp_path / "a.md"
    target.write_bytes(b"old\r\ncontent")
    settings = WorkspaceSettings(
        root=tmp_path,
        manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
    )
    store = _FailingManifestStore(settings.manifest_path)
    engine = WorkspaceEngine(
        settings=settings,
        manifest_store=cast(WorkspaceManifestStore, store),
    )

    with pytest.raises(WorkspaceIOError, match="manifest unavailable"):
        engine.write_text(
            "workspace:a.md",
            "new content",
            overwrite=True,
        )

    assert target.read_bytes() == b"old\r\ncontent"
    assert engine.load_manifest() == WorkspaceManifest()


def test_workspace_write_text_rejects_stale_expected_digest(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("old", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    before = engine.inspect("workspace:a.md")
    (tmp_path / "a.md").write_text("changed", encoding="utf-8")

    with pytest.raises(WorkspaceContractError, match="digest mismatch"):
        engine.write_text(
            "workspace:a.md",
            "new",
            overwrite=True,
            expected_digest=before.digest,
        )

    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "changed"


def test_workspace_expected_digest_hashes_exact_same_stat_base_bytes(
    tmp_path: Path,
) -> None:
    target = tmp_path / "a.md"
    target.write_text("old", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    before = engine.reconcile().manifest.resources[0]
    old_stat = target.stat()
    target.write_text("new", encoding="utf-8")
    os.utime(
        target,
        ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns),
    )

    with pytest.raises(WorkspaceContractError, match="digest mismatch"):
        engine.write_text(
            "workspace:a.md",
            "replacement",
            overwrite=True,
            expected_digest=before.digest,
        )

    assert target.read_text(encoding="utf-8") == "new"


def test_workspace_expected_digest_linearizes_competing_engine_writes(
    tmp_path: Path,
) -> None:
    target = tmp_path / "a.md"
    target.write_text("base", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    expected = engine.reconcile().manifest.resources[0].digest
    barrier = Barrier(2)

    def write(text: str) -> str:
        barrier.wait(timeout=1.0)
        try:
            engine.write_text(
                "workspace:a.md",
                text,
                overwrite=True,
                expected_digest=expected,
            )
        except WorkspaceContractError:
            return "conflict"
        return text

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(write, ("first", "second")))

    assert results.count("conflict") == 1
    winner = next(result for result in results if result != "conflict")
    assert target.read_text(encoding="utf-8") == winner


def test_workspace_write_text_rejects_ignored_parent(tmp_path: Path) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    with pytest.raises(WorkspaceContractError, match="ignored"):
        engine.write_text("workspace:.git/config", "unsafe")


def test_workspace_patch_text_replaces_exact_match(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello world", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    before = engine.inspect("workspace:a.md")

    record = engine.patch_text(
        "workspace:a.md",
        old_text="world",
        new_text="TinySoul",
        expected_digest=before.digest,
    )

    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "hello TinySoul"
    assert record.link == "workspace:a.md"
    assert record.digest != before.digest


def test_workspace_patch_text_rejects_ambiguous_or_stale_patch(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("same same", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    with pytest.raises(WorkspaceContractError, match="not unique"):
        engine.patch_text("workspace:a.md", old_text="same", new_text="other")
    with pytest.raises(WorkspaceContractError, match="digest mismatch"):
        engine.patch_text(
            "workspace:a.md",
            old_text="same same",
            new_text="other",
            expected_digest="stale",
        )


def test_workspace_trash_resource_removes_file_and_manifest(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    engine.reconcile()

    record = engine.trash_resource(
        "workspace:a.md",
        reason="test",
    ).original

    assert record.link == "workspace:a.md"
    assert not (tmp_path / "a.md").exists()
    assert engine.load_manifest().resources == ()


def test_workspace_trash_restore_preserves_lifecycle_metadata(tmp_path: Path) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    created = engine.write_text(
        "workspace:draft.md",
        "draft",
        retention=WorkspaceRetention.TURN,
        owner_turn_id="turn_1",
    )
    created = engine.set_description(
        created.link,
        "Temporary draft",
        expected_digest=created.digest,
    )

    trash = engine.trash_resource(
        created.link,
        reason="test_restore",
        source_turn_id="turn_1",
    )
    restored = engine.restore_resource(trash.ref)

    assert restored.retention is WorkspaceRetention.TURN
    assert restored.owner_turn_id == "turn_1"
    assert restored.description == "Temporary draft"
    assert (tmp_path / "draft.md").read_text(encoding="utf-8") == "draft"
    assert engine.trash_items() == ()


def test_workspace_trash_uses_current_disk_digest_after_external_change(
    tmp_path: Path,
) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    created = engine.write_text("workspace:draft.md", "old")
    engine.set_description(
        created.link,
        "Old description",
        expected_digest=created.digest,
    )
    (tmp_path / "draft.md").write_text("new", encoding="utf-8")

    trash = engine.trash_resource(created.link, reason="external_change")
    restored = engine.restore_resource(trash.ref)

    assert restored.digest != created.digest
    assert restored.description == ""
    assert (tmp_path / "draft.md").read_text(encoding="utf-8") == "new"


def test_workspace_missing_active_resource_exposes_trash_restore_ref(
    tmp_path: Path,
) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    engine.write_text("workspace:draft.md", "draft")
    trash = engine.trash_resource("workspace:draft.md", reason="context_pressure")

    with pytest.raises(WorkspaceTrashRestoreRequired) as exc_info:
        engine.inspect("workspace:draft.md")

    assert exc_info.value.link == "workspace:draft.md"
    assert exc_info.value.trash_ref == trash.ref


def test_workspace_explicit_delete_requires_manual_restore(tmp_path: Path) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    engine.write_text("workspace:draft.md", "draft")
    engine.trash_resource("workspace:draft.md", reason="workspace.delete")

    with pytest.raises(WorkspaceContractError, match="does not exist"):
        engine.inspect("workspace:draft.md")

    assert engine.trash_items()[0].original.link == "workspace:draft.md"


def test_workspace_pressure_rolls_back_prior_moves_when_a_later_move_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    for name in ("a.txt", "b.txt"):
        engine.write_text(
            f"workspace:{name}",
            name,
            retention=WorkspaceRetention.EPHEMERAL,
        )
    original = engine.trash_resource
    calls = 0

    def fail_second(
        link: WorkspaceLink | str,
        *,
        reason: str,
        source_turn_id: str = "",
    ):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise WorkspaceIOError("injected failure")
        return original(
            link,
            reason=reason,
            source_turn_id=source_turn_id,
        )

    monkeypatch.setattr(engine, "trash_resource", fail_second)

    with pytest.raises(WorkspaceIOError, match="injected failure"):
        WorkspacePressureReclaimer(engine).reclaim(required_chars=10000)

    assert {record.link for record in engine.snapshot().resources} == {
        "workspace:a.txt",
        "workspace:b.txt",
    }
    assert engine.trash_items() == ()


def test_workspace_pressure_only_trashes_explicitly_reclaimable_resources(
    tmp_path: Path,
) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    engine.write_text(
        "workspace:temporary.txt",
        "temporary",
        retention=WorkspaceRetention.EPHEMERAL,
        owner_turn_id="turn_1",
    )
    engine.write_text(
        "workspace:daily.txt",
        "daily",
        retention=WorkspaceRetention.DAY,
        owner_turn_id="turn_1",
    )

    report = WorkspacePressureReclaimer(engine).reclaim(
        required_chars=1,
        turn_id="turn_1",
    )

    assert report.removed_links == ("workspace:temporary.txt",)
    assert tuple(record.link for record in engine.snapshot().resources) == (
        "workspace:daily.txt",
    )
    assert len(engine.trash_items()) == 1


def test_workspace_manifest_v1_migrates_lifecycle_defaults() -> None:
    manifest = WorkspaceManifest.from_json(
        {
            "schema_version": 1,
            "revision": 3,
            "resources": [
                {
                    "link": "workspace:old.md",
                    "relative_path": "old.md",
                    "kind": "text",
                    "media_type": "text/markdown",
                    "suffix": ".md",
                    "summary": "Markdown text, 3 bytes",
                    "size": 3,
                    "mtime_ns": 1,
                    "digest": "abc",
                }
            ],
        }
    )

    assert manifest.schema_version == 3
    assert manifest.day == ""
    assert manifest.resources[0].retention is WorkspaceRetention.DAY
    assert manifest.resources[0].owner_turn_id == ""


def test_workspace_prepare_task_input_rejects_empty_links(tmp_path: Path) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    with pytest.raises(WorkspaceContractError, match="at least one"):
        engine.prepare_task_input(())


def test_workspace_describe_rejects_internal_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "workspace_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, manifest_path=manifest_path)
    ).build()

    with pytest.raises(WorkspaceContractError, match="internal"):
        engine.inspect("workspace:workspace_manifest.json")


def test_workspace_describe_executor_updates_manifest_and_working_patch(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    bus = SignalBus()
    context_engine = ContextEngineBuilder(system_text="system").build()
    context_engine.begin_turn("user asks")
    llm = FakeLLMRunner(answer={"description": "A small greeting document."})
    llm_action = LLMActionTaskRunner(llm_runner=llm, context=context_engine)
    execution = _execution(
        "workspace.describe",
        {"target_link": "workspace:a.md"},
    )

    result = WorkspaceDescribeExecutor(engine, bus, llm_action).execute(
        execution,
        ActionExecutionContext(signal_bus=bus),
    )

    assert result.status.value == "success"
    assert result.payload["summary"] == "Markdown text, 5 bytes"
    assert result.payload["description"] == "A small greeting document."
    assert engine.load_manifest().resources[0].link == "workspace:a.md"
    snapshot = _workspace_snapshot_payload(bus)
    assert snapshot["revision"] == engine.load_manifest().revision
    resources = snapshot["resources"]
    assert isinstance(resources, list)
    resource = resources[0]
    assert isinstance(resource, dict)
    assert resource["summary"] == (
        "Markdown text, 5 bytes. A small greeting document."
    )


def test_workspace_write_executor_generates_text_inside_action(
    tmp_path: Path,
) -> None:
    (tmp_path / "ref.md").write_text("reference text", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
            max_read_chars=100,
        )
    ).build()
    context_engine = ContextEngineBuilder(system_text="sys").build()
    context_engine.begin_turn("user asks")
    bus = SignalBus()
    llm = FakeLLMRunner({"text": "generated text"})
    execution = _execution(
        "workspace.write",
        {
            "target_link": "workspace:a.md",
            "instruction": "Create a short note.",
            "reference_links": ["workspace:ref.md"],
        },
    )

    llm_action = LLMActionTaskRunner(llm_runner=llm, context=context_engine)
    result = WorkspaceWriteExecutor(
        workspace=engine,
        bus=bus,
        llm_action=llm_action,
    ).execute(execution, ActionExecutionContext(signal_bus=bus))

    assert result.status.value == "success"
    assert result.payload["written"] is True
    assert result.payload["link"] == "workspace:a.md"
    assert "text" not in result.payload
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "generated text"
    target_prompt = _task_call_text_for_label(
        llm.calls[0],
        "task_prompt:input:workspace_write_target",
    )
    reference_prompt = _task_call_text_for_label(
        llm.calls[0],
        "task_prompt:input:workspace:reference:workspace:ref.md:prefix:100",
    )
    assert "link: workspace:a.md" in target_prompt
    assert "reference text" in reference_prompt
    snapshot = _workspace_snapshot_payload(bus)
    resources = snapshot["resources"]
    assert isinstance(resources, list)
    assert {item["link"] for item in resources if isinstance(item, dict)} == {
        "workspace:a.md",
        "workspace:ref.md",
    }
    first_resource = next(
        item
        for item in resources
        if isinstance(item, dict) and item.get("link") == "workspace:a.md"
    )
    assert isinstance(first_resource, dict)
    assert first_resource["link"] == "workspace:a.md"

def test_workspace_patch_executor_failure_is_local_result(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    bus = SignalBus()
    execution = _execution(
        "workspace.patch",
        {"target_link": "workspace:a.md", "old_text": "missing", "new_text": "x"},
    )

    result = WorkspacePatchExecutor(engine, bus).execute(
        execution,
        ActionExecutionContext(signal_bus=bus),
    )

    assert result.status.value == "failed"
    assert "not found" in result.model_feedback
    assert bus.consume_namespace("context") == ()


def test_workspace_delete_executor_emits_empty_workspace_snapshot(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    bus = SignalBus()
    execution = _execution("workspace.delete", {"target_link": "workspace:a.md"})

    result = WorkspaceDeleteExecutor(engine, bus).execute(
        execution,
        ActionExecutionContext(signal_bus=bus),
    )

    assert result.status.value == "success"
    assert result.payload["deleted"] is True
    assert not (tmp_path / "a.md").exists()
    snapshot = _workspace_snapshot_payload(bus)
    assert snapshot["resources"] == []



def test_workspace_rewrite_executor_loads_target_and_references_inside_action(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.md").write_text("old text", encoding="utf-8")
    (tmp_path / "ref.md").write_text("reference text", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
            max_read_chars=100,
        )
    ).build()
    context_engine = ContextEngineBuilder(system_text="sys").build()
    context_engine.begin_turn("user asks")
    bus = SignalBus()
    llm = FakeLLMRunner({"text": "new text"})
    execution = _execution(
        "workspace.rewrite",
        {
            "target_link": "workspace:target.md",
            "instruction": "Rewrite tersely.",
            "reference_links": ["workspace:ref.md"],
        },
    )

    llm_action = LLMActionTaskRunner(llm_runner=llm, context=context_engine)
    result = WorkspaceRewriteExecutor(
        workspace=engine,
        bus=bus,
        llm_action=llm_action,
    ).execute(execution, ActionExecutionContext(signal_bus=bus))

    assert result.status.value == "success"
    assert result.payload["rewritten"] is True
    assert result.payload["link"] == "workspace:target.md"
    assert "text" not in result.payload
    assert (tmp_path / "target.md").read_text(encoding="utf-8") == "new text"
    target_prompt = _task_call_text_for_label(
        llm.calls[0],
        "task_prompt:input:workspace:target:workspace:target.md:prefix:100",
    )
    reference_prompt = _task_call_text_for_label(
        llm.calls[0],
        "task_prompt:input:workspace:reference:workspace:ref.md:prefix:100",
    )
    assert "# Workspace Target" in target_prompt
    assert "old text" in target_prompt
    assert "# Workspace Reference" in reference_prompt
    assert "reference text" in reference_prompt
    snapshot = _workspace_snapshot_payload(bus)
    resources = snapshot["resources"]
    assert isinstance(resources, list)
    assert {item["link"] for item in resources if isinstance(item, dict)} == {
        "workspace:ref.md",
        "workspace:target.md",
    }
    first_resource = next(
        item
        for item in resources
        if isinstance(item, dict) and item.get("link") == "workspace:target.md"
    )
    assert isinstance(first_resource, dict)
    assert first_resource["link"] == "workspace:target.md"


def test_workspace_rewrite_executor_rejects_target_changed_after_prompt(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.md"
    target.write_text("old text", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
            max_read_chars=100,
        )
    ).build()
    context_engine = ContextEngineBuilder(system_text="sys").build()
    context_engine.begin_turn("user asks")
    bus = SignalBus()
    def change_target() -> None:
        target.write_text("changed elsewhere", encoding="utf-8")

    llm = FakeLLMRunner(
        {"text": "new text"},
        on_run=change_target,
    )
    execution = _execution(
        "workspace.rewrite",
        {
            "target_link": "workspace:target.md",
            "instruction": "Rewrite tersely.",
        },
    )

    llm_action = LLMActionTaskRunner(llm_runner=llm, context=context_engine)
    result = WorkspaceRewriteExecutor(
        workspace=engine,
        bus=bus,
        llm_action=llm_action,
    ).execute(execution, ActionExecutionContext(signal_bus=bus))

    assert result.status.value == "failed"
    assert "digest mismatch" in result.model_feedback
    assert target.read_text(encoding="utf-8") == "changed elsewhere"
    assert bus.consume_namespace("context") == ()


def _message_text(message: UserMessage) -> str:
    return "\n".join(part.text for part in message.parts if isinstance(part, TextPart))


def _workspace_snapshot_payload(bus: SignalBus) -> JsonObject:
    signals = bus.consume_namespace("context")
    assert len(signals) == 1
    assert signals[0].name == SIGNAL_WORKSPACE_SYNC
    return signals[0].payload



def _task_call_text_for_label(call: TaskCall, label: str) -> str:
    for message in call.messages.messages:
        if message.label != label:
            continue
        return "\n".join(
            part.text for part in message.parts if isinstance(part, TextPart)
        )
    raise AssertionError(f"Missing message label: {label}")


def _execution(action_name: str, params: JsonObject) -> ActionExecution:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="workspace", description="Workspace."),),
        actions=(
            ActionSpec(
                name=action_name,
                domain="workspace",
                tool=ActionToolSpec(
                    name=action_name,
                    description="Scan.",
                    schema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                ),
                semantic=ActionSemanticSpec(),
                runtime=ActionRuntimeSpec(),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler=action_name,
                ),
            ),
        ),
    )
    preparation = ActionExecutionBuilder().prepare_batch(
        (ActionCall("call_1", action_name, params, 1),),
        catalog=catalog,
        scope=RunScope().push(RunLevel.PHASE, "phase3"),
        batch_id="batch_1",
    )
    return preparation.batch.executions[0]
