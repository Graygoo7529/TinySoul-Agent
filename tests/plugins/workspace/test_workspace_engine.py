from __future__ import annotations

from datetime import date as CalendarDate
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.workspace.projection import (
    SIGNAL_WORKSPACE_SYNC,
    workspace_segment_registration,
)
import asyncio

from collections.abc import Callable
import os
from pathlib import Path
from typing import cast

import pytest

from tinysoul.kernel.action.call import ActionCall, ActionExecution
from tinysoul.kernel.action.execution.preparation import ActionExecutionBuilder
from tinysoul.kernel.action.catalog.catalog import ActionCatalog
from tinysoul.kernel.action.execution.executor import ActionExecutionContext
from tinysoul.kernel.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.kernel.action.catalog.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.kernel.context import (
    ContextEngineBuilder,
    PromptReferenceError,
)
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.messages import ImagePart, TextPart, UserMessage
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import (
    AnswerFormat,
    JsonAnswer,
    RawResponse,
    TaskFailure,
    TaskFailureReason,
    TaskFailureScope,
    TaskResult,
    TextAnswer,
)
from tinysoul.kernel.loop import TurnPreparationRequest
from tinysoul.infra.time import CalendarDay
from tinysoul.runtime import RunLevel, RunScope, SignalBus
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
import tinysoul.plugins.workspace.engine as workspace_engine_module
from tinysoul.plugins.workspace import (
    WorkspaceContractError,
    WorkspaceAnalysisSettings,
    WorkspaceBundleWrite,
    WorkspaceDiscoverySkipKind,
    WorkspaceEngineBuilder,
    WorkspaceLink,
    WorkspaceManifest,
    WorkspacePromptInput,
    WorkspacePromptReferenceResolver,
    WorkspaceReconciliationError,
    WorkspaceReconcileStatus,
    WorkspaceResourceKind,
    WorkspaceSearchScope,
    WorkspaceSearchScopeKind,
    WorkspaceSearchSettings,
    WorkspaceSettings,
    parse_workspace_settings,
)


from tinysoul.plugins.workspace.projection import WorkspaceTurnPreparationHandler
from tinysoul.plugins.workspace import WorkspaceTextSlice
from tinysoul.plugins.workspace.engine import WorkspaceEngine
from tinysoul.plugins.workspace.storage.manifest import WorkspaceManifestStore
from tinysoul.plugins.workspace.actions import (
    WorkspaceAnalyzeExecutor,
    WorkspaceExecutor,
)

DAY = CalendarDay.parse("2026-07-12")


class FakeLLMRunner:
    def __init__(
        self,
        answer: JsonObject | None = None,
        on_run: Callable[[], None] | None = None,
        failure: TaskFailure | None = None,
    ) -> None:
        self.calls: list[TaskCall] = []
        self.answer = answer or {"text": "new text"}
        self.on_run = on_run
        self.failure = failure

    async def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        if self.on_run is not None:
            self.on_run()
        raw_response = RawResponse(
            answer_text="{}",
            model_id="fake",
            provider_id="fake",
        )
        if self.failure is not None:
            return TaskResult.failure_result(
                raw_response=raw_response,
                failure=self.failure,
            )
        if call.settings.answer_format is AnswerFormat.TEXT:
            text = self.answer.get("text")
            assert isinstance(text, str)
            answer = TextAnswer(text)
        else:
            answer = JsonAnswer(self.answer)
        return TaskResult.success(
            raw_response=raw_response,
            answer=answer,
            tool_calls=(),
        )


def test_workspace_settings_parse_search_and_analysis_tables(tmp_path: Path) -> None:
    settings = parse_workspace_settings(
        {
            "search": {
                "max_scan_chars": 1234,
                "max_excerpt_chars": 321,
                "max_result_chars": 4321,
            },
            "analysis": {
                "max_reference_links": 3,
                "max_source_chars": 6000,
                "max_chars_per_reference": 2000,
            },
        },
        project_root=tmp_path,
    )

    assert settings.search.max_scan_chars == 1234
    assert settings.search.max_excerpt_chars == 321
    assert settings.search.max_result_chars == 4321
    assert settings.analysis.max_reference_links == 3
    assert settings.analysis.max_source_chars == 6000
    assert settings.analysis.max_chars_per_reference == 2000


def test_workspace_settings_reject_unknown_nested_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        parse_workspace_settings(
            {"search": {"semantic_provider": "implicit"}},
            project_root=tmp_path,
        )

    assert exc_info.value.key == "workspace.search.semantic_provider"


def test_workspace_search_excerpt_budget_must_contain_query() -> None:
    with pytest.raises(ConfigError) as exc_info:
        WorkspaceSearchSettings(
            max_query_chars=20,
            max_excerpt_chars=10,
        )

    assert exc_info.value.key == "workspace.search.max_excerpt_chars"


def test_workspace_document_read_is_bounded(local_tmp: Path) -> None:
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


def test_workspace_link_rejects_unsafe_paths() -> None:
    assert str(WorkspaceLink.parse("workspace:docs/a.md")) == "workspace:docs/a.md"
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("file:docs/a.md")
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("workspace:../secret.md")
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("workspace:C:/secret.md")


def test_workspace_scan_manifest_file_does_not_hide_root(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    manifest_path = tmp_path / "workspace_manifest.json"
    WorkspaceManifestStore(manifest_path).save(WorkspaceManifest())
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, manifest_path=manifest_path)
    ).build()

    result = engine.reconcile()

    assert [resource.link for resource in result.resources] == ["workspace:a.md"]
    assert all(
        item.link != "workspace:workspace_manifest.json" for item in result.resources
    )


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


async def test_workspace_prompt_resolver_loads_images_and_rejects_documents(
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
    resolver = WorkspacePromptReferenceResolver(WorkspaceService(engine))

    blocks = await resolver.resolve_reference("workspace:image.png")

    assert any(isinstance(part, ImagePart) for part in blocks[0].message.parts)
    with pytest.raises(PromptReferenceError) as raised:
        await resolver.resolve_reference("workspace:report.pdf")
    assert raised.value.reason == "conversion_required"


async def test_workspace_prompt_resolver_rejects_image_with_invalid_signature(
    tmp_path: Path,
) -> None:
    (tmp_path / "image.png").write_bytes(b"not a png")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    resolver = WorkspacePromptReferenceResolver(WorkspaceService(engine))

    with pytest.raises(PromptReferenceError) as raised:
        await resolver.resolve_reference("workspace:image.png")

    assert raised.value.reason == "invalid_image_resource"


async def test_workspace_turn_preparation_projects_manifest_into_context(
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
    context.register_segment(workspace_segment_registration(workspace))
    turn_id = context.begin_turn("hello")
    await context.open_segments(DAY.value)
    scope = RunScope().push(RunLevel.AGENT, "program").push(RunLevel.TURN, turn_id)
    bus = SignalBus()
    handler = WorkspaceTurnPreparationHandler(
        workspace,
        runtime_bridge=RuntimeWorkspaceBridge(),
    )

    for signal in await handler.prepare(
        TurnPreparationRequest(
            turn_id=turn_id,
            turn_input="hello",
            active_day=DAY,
            scope=scope,
        )
    ):
        bus.emit(signal)
    assert await context.consume_signals(bus) == ()

    working = context.segment_snapshot("workspace")
    assert working["resources"] == [
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
    assert "workspace:a.md" in rendered
    assert "abc" in rendered
    assert "workspace:b.md" in rendered


async def test_workspace_prompt_reference_resolver_returns_prefix_block(
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
    resolver = WorkspacePromptReferenceResolver(WorkspaceService(engine))

    blocks = await resolver.resolve_reference("workspace:a.md")

    assert len(blocks) == 1
    assert (
        blocks[0].label
        == "task_prompt:input:workspace:reference:workspace:a.md:prefix:3"
    )
    text = _message_text(blocks[0].message)
    assert "# Workspace Reference" in text
    assert "link: workspace:a.md" in text
    assert "abc" in text
    assert "truncated: true" in text


async def test_workspace_prompt_reference_resolver_returns_target_block(
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
    resolver = WorkspacePromptReferenceResolver(WorkspaceService(engine))

    blocks = await resolver.resolve_target("workspace:a.md")

    assert len(blocks) == 1
    assert (
        blocks[0].label == "task_prompt:input:workspace:target:workspace:a.md:prefix:3"
    )
    text = _message_text(blocks[0].message)
    assert "# Workspace Target" in text
    assert "link: workspace:a.md" in text
    assert "abc" in text
    assert "truncated: true" in text


def test_workspace_read_text_range_continues_inside_long_line(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("abcdef\nsecond\n", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, max_read_chars=4)
    ).build()

    first = engine.read_text_range(
        "workspace:a.md",
        start_line=1,
        end_line=1,
        max_chars=3,
    )
    second = engine.read_text_range(
        "workspace:a.md",
        start_line=1,
        end_line=1,
        cursor=first.page.next_cursor or 0,
        max_chars=10,
    )

    assert first.page.text == "abc"
    assert first.page.truncated is True
    assert first.page.next_cursor == 3
    assert first.page.next_position is not None
    assert (first.page.next_position.line, first.page.next_position.column) == (1, 4)
    assert second.page.text == "def\n"
    assert second.page.truncated is False
    assert second.max_chars == 4


def test_workspace_read_text_range_normalizes_crlf_unicode_and_reports_eof(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.txt").write_bytes("alpha\r\n中文".encode())
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    engine.reconcile()

    result = engine.read_text_range(
        "workspace:a.txt",
        start_line=2,
        end_line=2,
    )

    assert result.page.text == "中文"
    assert result.page.actual_start is not None
    assert result.page.actual_start.line == 2
    assert result.page.actual_start.column == 1
    assert result.page.actual_end is not None
    assert result.page.actual_end.column == 2
    assert result.page.eof_reached is True
    assert result.page.truncated is False


async def test_workspace_read_action_returns_foldable_text_range(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, max_read_chars=7)
    ).build()

    result = await _executor(engine).execute(
        _execution(
            "workspace.read",
            {"link": "workspace:a.md", "start_line": 2, "end_line": 3},
        ),
        ActionExecutionContext(),
    )

    assert result.status.value == "success"
    assert result.payload["text"] == "two\nthr"
    assert result.payload["truncated"] is True
    assert result.trace_projection is not None
    assert result.trace_projection.origin_refs == ("workspace:a.md",)
    assert "text" not in result.trace_projection.canonical_payload


def test_workspace_search_text_scopes_directory_and_returns_fragments(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src2").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        "before\nWorkspaceContractError here\nafter\n",
        encoding="utf-8",
    )
    (tmp_path / "src2" / "b.py").write_text(
        "WorkspaceContractError elsewhere\n",
        encoding="utf-8",
    )
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    engine.reconcile()

    result = engine.search(
        query="WorkspaceContractError",
        scope=WorkspaceSearchScope(
            WorkspaceSearchScopeKind.DIRECTORY,
            "workspace:src/",
        ),
        case_sensitive=True,
    )

    assert result.coverage.complete is True
    assert result.match_line_count == 1
    assert len(result.fragments) == 1
    assert result.fragments[0].link == "workspace:src/a.py"
    assert (result.fragments[0].start_line, result.fragments[0].end_line) == (1, 3)
    assert "WorkspaceContractError here" in result.fragments[0].text


@pytest.mark.parametrize(
    ("kind", "locator"),
    (
        (WorkspaceSearchScopeKind.FILE, "workspace:a.md"),
        (WorkspaceSearchScopeKind.DIRECTORY, "workspace:src/"),
        (WorkspaceSearchScopeKind.WORKSPACE, ""),
    ),
)
def test_workspace_search_scope_serializes_tool_contract(
    kind: WorkspaceSearchScopeKind,
    locator: str,
) -> None:
    scope = WorkspaceSearchScope(kind, locator)

    assert scope.to_json() == {"kind": kind.value, "locator": locator}


def test_workspace_search_text_returns_line_hints_after_fragment_limit(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text(
        "needle one\nmiddle\nneedle two\n",
        encoding="utf-8",
    )
    (tmp_path / "b.md").write_text("needle three\n", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            search=WorkspaceSearchSettings(context_lines=0, default_top_k=1),
        )
    ).build()
    engine.reconcile()

    result = engine.search(
        query="needle",
        scope=WorkspaceSearchScope(WorkspaceSearchScopeKind.WORKSPACE),
        top_k=1,
    )

    assert len(result.fragments) == 1
    assert [(item.link, item.line) for item in result.line_hints] == [
        ("workspace:a.md", 3),
        ("workspace:b.md", 1),
    ]
    assert result.truncated is True


def test_workspace_search_text_reports_incomplete_scan_budget(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("x" * 20 + "needle", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            search=WorkspaceSearchSettings(max_scan_chars=10),
        )
    ).build()
    engine.reconcile()

    result = engine.search(
        query="needle",
        scope=WorkspaceSearchScope(
            WorkspaceSearchScopeKind.FILE,
            "workspace:a.md",
        ),
    )

    assert result.fragments == ()
    assert result.coverage.complete is False
    assert result.coverage.reason == "scan_limit"
    assert result.coverage.characters_scanned == 10


def test_workspace_search_text_workspace_scope_centers_long_match(
    tmp_path: Path,
) -> None:
    (tmp_path / "b.txt").write_text("no match", encoding="utf-8")
    (tmp_path / "a.txt").write_text(
        "x" * 700 + "Needle" + "z" * 700,
        encoding="utf-8",
    )
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            search=WorkspaceSearchSettings(
                max_query_chars=20,
                max_excerpt_chars=80,
                max_result_chars=4000,
            ),
        )
    ).build()
    engine.reconcile()

    result = engine.search(
        query="needle",
        scope=WorkspaceSearchScope(WorkspaceSearchScopeKind.WORKSPACE),
    )

    assert len(result.fragments) == 1
    fragment = result.fragments[0]
    assert fragment.link == "workspace:a.txt"
    assert "Needle" in fragment.text
    assert fragment.excerpt_truncated is True
    assert fragment.start_column is not None
    assert fragment.start_column > 1


def test_workspace_search_text_casefold_excerpt_uses_original_columns(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.txt").write_text(
        "ß" * 700 + "Needle" + "z" * 700,
        encoding="utf-8",
    )
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            search=WorkspaceSearchSettings(
                max_query_chars=20,
                max_excerpt_chars=80,
                max_result_chars=4000,
            ),
        )
    ).build()
    engine.reconcile()

    result = engine.search(
        query="needle",
        scope=WorkspaceSearchScope(WorkspaceSearchScopeKind.WORKSPACE),
    )

    fragment = result.fragments[0]
    assert "Needle" in fragment.text
    assert fragment.start_column is not None
    assert fragment.start_column <= 701
    assert fragment.end_column is not None
    assert fragment.end_column >= 706


def test_workspace_search_text_casefold_match_can_expand_source_character(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.txt").write_text(
        "x" * 700 + "Straße" + "z" * 700,
        encoding="utf-8",
    )
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            search=WorkspaceSearchSettings(
                max_query_chars=20,
                max_excerpt_chars=80,
                max_result_chars=4000,
            ),
        )
    ).build()
    engine.reconcile()

    result = engine.search(
        query="STRASSE",
        scope=WorkspaceSearchScope(WorkspaceSearchScopeKind.WORKSPACE),
    )

    fragment = result.fragments[0]
    assert "Straße" in fragment.text
    assert fragment.start_column is not None
    assert fragment.start_column <= 701
    assert fragment.end_column is not None
    assert fragment.end_column >= 706


def test_workspace_search_text_skips_invalid_utf8_with_partial_coverage(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.txt").write_bytes(b"\xff\xfe")
    (tmp_path / "b.txt").write_text("needle", encoding="utf-8")
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    engine.reconcile()

    result = engine.search(
        query="needle",
        scope=WorkspaceSearchScope(WorkspaceSearchScopeKind.WORKSPACE),
    )

    assert [fragment.link for fragment in result.fragments] == ["workspace:b.txt"]
    assert result.coverage.complete is False
    assert result.coverage.reason == "unreadable_text"
    assert result.coverage.skipped_count == 1


async def test_workspace_search_action_returns_foldable_fragments(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("needle\n", encoding="utf-8")
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    engine.reconcile()

    result = await _executor(engine).execute(
        _execution(
            "workspace.search",
            {
                "query": "needle",
                "scope": {"kind": "file", "locator": "workspace:a.md"},
            },
        ),
        ActionExecutionContext(),
    )

    assert result.status.value == "success"
    expected_scope = {"kind": "file", "locator": "workspace:a.md"}
    assert result.payload["scope"] == expected_scope
    fragments = result.payload["fragments"]
    assert isinstance(fragments, list)
    fragment = fragments[0]
    assert isinstance(fragment, dict)
    assert fragment["text"] == "needle\n"
    assert result.trace_projection is not None
    compact = result.trace_projection.canonical_payload
    assert compact["scope"] == expected_scope
    compact_fragments = compact["fragments"]
    assert isinstance(compact_fragments, list)
    compact_fragment = compact_fragments[0]
    assert isinstance(compact_fragment, dict)
    assert "text" not in compact_fragment


async def test_workspace_search_action_rejects_legacy_scope_shape(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("needle\n", encoding="utf-8")
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    engine.reconcile()

    result = await _executor(engine).execute(
        _execution(
            "workspace.search",
            {
                "query": "needle",
                "scope": {"kind": "file", "link": "workspace:a.md"},
            },
        ),
        ActionExecutionContext(),
    )

    assert result.status.value == "failed"
    assert result.failure is not None
    assert result.failure.reason == "request_conflict"


async def test_workspace_analyze_returns_grounded_standard_result(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("beta\n", encoding="utf-8")
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    context_engine = ContextEngineBuilder(system_text="system").build()
    context_engine.begin_turn("analyze files")
    await context_engine.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner(
        answer={"answer": "Alpha and beta are present.", "source_ids": ["source_1"]}
    )
    executor = WorkspaceAnalyzeExecutor(
        workspace=WorkspaceService(engine),
        llm_action=LLMActionTaskRunner(llm_runner=llm, context=context_engine),
    )
    before = engine.reconcile().manifest

    result = await executor.execute(
        _execution(
            "workspace.analyze",
            {
                "intent": "Compare the files.",
                "reference_links": ["workspace:a.md", "workspace:b.md"],
            },
        ),
        ActionExecutionContext(),
    )

    assert result.status.value == "success"
    assert result.payload["answer"] == "Alpha and beta are present."
    assert result.payload["sources"] == [
        {
            "source_id": "source_1",
            "link": "workspace:a.md",
            "size": engine.inspect("workspace:a.md").size,
            "range": {"start_line": 1, "end_line": 1},
        }
    ]
    assert result.trace_projection is None
    assert engine.load_manifest() == before
    assert len(llm.calls) == 1
    assert "alpha" in _task_call_text_for_label(
        llm.calls[0], "task_prompt:input:workspace:analysis:source_1"
    )


async def test_workspace_analyze_budget_failure_does_not_call_llm(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("abcdef", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            analysis=WorkspaceAnalysisSettings(
                max_chars_per_reference=5,
                max_source_chars=10,
            ),
        )
    ).build()
    context_engine = ContextEngineBuilder(system_text="system").build()
    context_engine.begin_turn("analyze files")
    await context_engine.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner(answer={"answer": "unused", "source_ids": ["source_1"]})

    result = await WorkspaceAnalyzeExecutor(
        workspace=WorkspaceService(engine),
        llm_action=LLMActionTaskRunner(llm_runner=llm, context=context_engine),
    ).execute(
        _execution(
            "workspace.analyze",
            {"intent": "Analyze.", "reference_links": ["workspace:a.md"]},
        ),
        ActionExecutionContext(),
    )

    assert result.status.value == "failed"
    assert result.payload["reason"] == "reference_chars_exceeded"
    assert result.payload["offending_link"] == "workspace:a.md"
    assert llm.calls == []


async def test_workspace_analyze_rejects_invented_source_id(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    context_engine = ContextEngineBuilder(system_text="system").build()
    context_engine.begin_turn("analyze files")
    await context_engine.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner(answer={"answer": "Invented.", "source_ids": ["source_99"]})

    result = await WorkspaceAnalyzeExecutor(
        workspace=WorkspaceService(engine),
        llm_action=LLMActionTaskRunner(llm_runner=llm, context=context_engine),
    ).execute(
        _execution(
            "workspace.analyze",
            {"intent": "Analyze.", "reference_links": ["workspace:a.md"]},
        ),
        ActionExecutionContext(),
    )

    assert result.status.value == "failed"
    assert result.failure is not None
    assert result.failure.reason == "unknown_analysis_source_ids"


async def test_workspace_analyze_requires_at_least_one_grounding_source(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    context_engine = ContextEngineBuilder(system_text="system").build()
    context_engine.begin_turn("analyze files")
    await context_engine.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner(answer={"answer": "Alpha is present.", "source_ids": []})

    result = await WorkspaceAnalyzeExecutor(
        workspace=WorkspaceService(engine),
        llm_action=LLMActionTaskRunner(llm_runner=llm, context=context_engine),
    ).execute(
        _execution(
            "workspace.analyze",
            {"intent": "Analyze.", "reference_links": ["workspace:a.md"]},
        ),
        ActionExecutionContext(),
    )

    assert result.status.value == "failed"
    assert result.failure is not None
    assert result.failure.reason == "invalid_analysis_source_ids"


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
    assert {item.link for item in engine.load_manifest().resources} == {
        "workspace:docs",
        "workspace:docs/a.md",
    }


def test_workspace_write_text_rejects_existing_without_overwrite(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.md").write_text("old", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    with pytest.raises(WorkspaceContractError, match="already exists"):
        engine.write_text("workspace:a.md", "new")


def test_workspace_write_text_rejects_ignored_parent(tmp_path: Path) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    with pytest.raises(WorkspaceContractError):
        engine.write_text("workspace:.git/config", "unsafe")


def test_workspace_prepare_task_input_rejects_empty_links(tmp_path: Path) -> None:
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()

    with pytest.raises(WorkspaceContractError):
        engine.prepare_task_input(())


def test_workspace_describe_rejects_internal_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "workspace_manifest.json"
    WorkspaceManifestStore(manifest_path).save(WorkspaceManifest())
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, manifest_path=manifest_path)
    ).build()

    with pytest.raises(WorkspaceContractError, match="internal"):
        engine.inspect("workspace:workspace_manifest.json")


def _message_text(message: UserMessage) -> str:
    return "\n".join(part.text for part in message.parts if isinstance(part, TextPart))


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


def _executor(engine: WorkspaceEngine) -> WorkspaceExecutor:
    return WorkspaceExecutor(
        WorkspaceService(engine),
        LLMActionTaskRunner(
            llm_runner=FakeLLMRunner(),
            context=ContextEngineBuilder(system_text="sys").build(),
        ),
        RuntimeWorkspaceBridge(),
    )


@pytest.mark.parametrize("overwrite", [False, True])
async def test_compose_uses_local_sources_and_commits_only_complete_text(
    tmp_path: Path, overwrite: bool
) -> None:
    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()
    if overwrite:
        engine.write_text("workspace:target.md", "old target")
    engine.write_text("workspace:ref.md", "source evidence")
    context = ContextEngineBuilder(system_text="system").build()
    context.begin_turn("compose")
    await context.open_segments(CalendarDate(2026, 9, 19))
    llm = FakeLLMRunner({"text": "complete result"})
    bus = SignalBus()
    executor = WorkspaceExecutor(
        WorkspaceService(engine),
        LLMActionTaskRunner(llm_runner=llm, context=context),
        RuntimeWorkspaceBridge(),
    )
    result = await executor.execute(
        _execution(
            "workspace.compose",
            {
                "target_link": "workspace:target.md",
                "instruction": "Use the evidence.",
                "reference_links": ["workspace:ref.md"],
                "overwrite": overwrite,
            },
        ),
        ActionExecutionContext(),
    )
    assert result.status.value == "success"
    assert engine.read_text("workspace:target.md").text == "complete result"
    assert len(llm.calls) == 1
    assert "text" not in result.payload
    assert any(item.link == "workspace:target.md" for item in engine.snapshot().resources)


async def test_compose_rejects_truncated_target_before_generating(
    tmp_path: Path,
) -> None:
    (tmp_path / "target.md").write_text("too much text", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, max_write_chars=4)
    ).build()
    context = ContextEngineBuilder(system_text="system").build()
    context.begin_turn("compose")
    await context.open_segments(CalendarDate(2026, 9, 19))
    llm = FakeLLMRunner({"text": "new"})
    executor = WorkspaceExecutor(
        WorkspaceService(engine),
        LLMActionTaskRunner(llm_runner=llm, context=context),
        RuntimeWorkspaceBridge(),
    )
    result = await executor.execute(
        _execution(
            "workspace.compose",
            {
                "target_link": "workspace:target.md",
                "instruction": "Change it.",
                "overwrite": True,
            },
        ),
        ActionExecutionContext(),
    )
    assert result.status.value == "failed"
    assert llm.calls == []
    assert (tmp_path / "target.md").read_text(encoding="utf-8") == "too much text"


async def test_workspace_owner_io_failure_crosses_bridge_without_raw_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tinysoul.plugins.workspace import WorkspaceIOError
    from tinysoul.runtime import RuntimeException

    engine = WorkspaceEngineBuilder(WorkspaceSettings(root=tmp_path)).build()

    def fail_write(*args, **kwargs):
        raise WorkspaceIOError("private /local/path secret")

    monkeypatch.setattr(engine, "write_text", fail_write)
    with pytest.raises(RuntimeException) as raised:
        await _executor(engine).execute(
            _execution(
                "workspace.write",
                {
                    "target_link": "workspace:a.md",
                    "text": "a",
                },
            ),
            ActionExecutionContext(),
        )
    assert raised.value.payload["module"] == "workspace"
    assert "private" not in str(raised.value.payload)
