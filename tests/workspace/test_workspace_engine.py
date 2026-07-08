from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.action.core.call import ActionCall, ActionExecution, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.llm_action import LLMActionTaskRunner
from tinysoul.action.core.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.context import ContextEngineBuilder, SIGNAL_WORKING_PATCH
from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import TextPart, UserMessage
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.runtime import RunLevel, RunScope, SignalBus
from tinysoul.workspace import (
    WorkspaceContractError,
    WorkspaceEngineBuilder,
    WorkspaceLink,
    WorkspacePromptInput,
    WorkspacePromptReferenceResolver,
    WorkspaceScanSkipKind,
    WorkspaceSettings,
    WorkspaceTextSlice,
)
from tinysoul.workspace.actions import (
    WorkspaceDeleteExecutor,
    WorkspaceDescribeExecutor,
    WorkspacePatchExecutor,
    WorkspaceRewriteExecutor,
    WorkspaceWriteExecutor,
    workspace_scan,
)


class FakeLLMRunner:
    def __init__(self, answer: JsonObject | None = None) -> None:
        self.calls: list[TaskCall] = []
        self.answer = answer or {"text": "new text"}

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return TaskResult.success(
            raw_response=RawResponse(
                answer_text="{}",
                model_id="fake",
                provider_id="fake",
            ),
            answer=JsonAnswer(self.answer),
            tool_calls=(),
        )


def test_workspace_link_rejects_unsafe_paths() -> None:
    assert str(WorkspaceLink.parse("workspace:docs/a.md")) == "workspace:docs/a.md"
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("file:docs/a.md")
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("workspace:../secret.md")
    with pytest.raises(WorkspaceContractError):
        WorkspaceLink.parse("workspace:C:/secret.md")


def test_workspace_scan_updates_manifest_and_emits_working_patch(tmp_path: Path) -> None:
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

    payload = workspace_scan(engine, bus)(execution, ActionExecutionContext(signal_bus=bus))

    assert payload["count"] == 1
    assert payload["resources"] == [
        {"link": "workspace:docs/a.md", "summary": ".md file, 5 bytes"}
    ]
    assert payload["skipped_count"] == 0
    assert payload["skip_counts"] == {}
    assert payload["limit_reached"] is False
    assert manifest_path.is_file()
    signals = bus.consume_namespace("context")
    assert len(signals) == 1
    assert signals[0].name == SIGNAL_WORKING_PATCH
    patch = signals[0].payload["patch"]
    assert isinstance(patch, dict)
    set_resources = patch["set_resources"]
    assert isinstance(set_resources, list)
    first_resource = set_resources[0]
    assert isinstance(first_resource, dict)
    assert first_resource["link"] == "workspace:docs/a.md"


def test_workspace_scan_manifest_file_does_not_hide_root(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    manifest_path = tmp_path / "workspace_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(root=tmp_path, manifest_path=manifest_path)
    ).build()

    result = engine.scan()

    assert [resource.link for resource in result.resources] == ["workspace:a.md"]
    assert result.skipped_count == 1
    assert result.skipped[0].kind is WorkspaceScanSkipKind.INTERNAL


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

    result = engine.scan()

    assert [resource.link for resource in result.resources] == ["workspace:a.md"]
    assert result.limit_reached is True


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
    assert engine.load_manifest().resources[0].link == "workspace:a.md"


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
    before = engine.describe("workspace:a.md")

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


def test_workspace_delete_resource_removes_file_and_manifest(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    engine = WorkspaceEngineBuilder(
        WorkspaceSettings(
            root=tmp_path,
            manifest_path=tmp_path / ".tinysoul" / "workspace_manifest.json",
        )
    ).build()
    engine.describe("workspace:a.md")

    record = engine.delete_resource("workspace:a.md")

    assert record.link == "workspace:a.md"
    assert not (tmp_path / "a.md").exists()
    assert engine.load_manifest().resources == ()


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
        engine.describe("workspace:workspace_manifest.json")


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
    execution = _execution("workspace.describe", {"link": "workspace:a.md"})

    result = WorkspaceDescribeExecutor(engine, bus).execute(
        execution,
        ActionExecutionContext(signal_bus=bus),
    )

    assert result.status.value == "success"
    assert result.payload["summary"] == ".md file, 5 bytes"
    assert engine.load_manifest().resources[0].link == "workspace:a.md"
    signals = bus.consume_namespace("context")
    assert signals[0].name == SIGNAL_WORKING_PATCH


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
    signals = bus.consume_namespace("context")
    patch = signals[0].payload["patch"]
    assert isinstance(patch, dict)
    set_resources = patch["set_resources"]
    assert isinstance(set_resources, list)
    first_resource = set_resources[0]
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


def test_workspace_delete_executor_emits_resource_removal(tmp_path: Path) -> None:
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
    signals = bus.consume_namespace("context")
    patch = signals[0].payload["patch"]
    assert isinstance(patch, dict)
    assert patch["remove_resources"] == ["workspace:a.md"]



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
    signals = bus.consume_namespace("context")
    patch = signals[0].payload["patch"]
    assert isinstance(patch, dict)
    set_resources = patch["set_resources"]
    assert isinstance(set_resources, list)
    first_resource = set_resources[0]
    assert isinstance(first_resource, dict)
    assert first_resource["link"] == "workspace:target.md"


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
