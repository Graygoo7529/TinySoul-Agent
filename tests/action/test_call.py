from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.action.core.call import (
    ActionBatch,
    ActionCall,
    ActionCallNormalizer,
    ActionExecution,
    ActionExecutionBuilder,
    ActionFramework,
)
from tinysoul.action.core.errors import ActionInvariantError
from tinysoul.action.core.hooks import ActionNormalizeHookPipeline, HookOutcome
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.action.core.result import ActionResult, ActionResultStage, ActionResultStatus
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RunScope


class RejectNormalizeHook:
    def check(self, item, context) -> HookOutcome:
        return HookOutcome.failed("Rejected during normalize")


def test_normalize_tool_calls_to_action_calls() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))
    tool_calls = (
        ToolCallRecord(
            id="call_1",
            name="core.answer",
            arguments={"text": "done"},
            kind=ToolKind.ACTION,
        ),
    )

    normalization = ActionCallNormalizer().normalize(tool_calls, catalog=catalog)
    calls = normalization.calls

    assert len(calls) == 1
    assert calls[0].action_name == "core.answer"
    assert calls[0].call_id == "call_1"
    assert calls[0].sequence == 1
    assert calls[0].params == {"text": "done"}
    assert normalization.results == ()


def test_normalizer_returns_result_for_non_action_tool_call() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments={"text": "done"},
                kind=ToolKind.CONTROL,
            ),
        ),
        catalog=catalog,
    )

    assert normalization.calls == ()
    assert normalization.results[0].call_id == "call_1"
    assert normalization.results[0].status is ActionResultStatus.FAILED
    assert normalization.results[0].stage is ActionResultStage.NORMALIZE


def test_normalizer_returns_result_for_invalid_action_arguments() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments={},
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )

    assert normalization.calls == ()
    assert normalization.results[0].status is ActionResultStatus.FAILED
    assert normalization.results[0].stage is ActionResultStage.NORMALIZE
    assert "Missing required action parameter" in normalization.results[0].model_feedback


def test_normalizer_returns_result_for_duplicate_call_id() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments={"text": "done"},
                kind=ToolKind.ACTION,
            ),
            ToolCallRecord(
                id="call_1",
                name="workspace.scan",
                arguments={},
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )

    assert len(normalization.calls) == 1
    assert normalization.results[0].call_id == "call_1"
    assert normalization.results[0].stage is ActionResultStage.NORMALIZE
    assert normalization.results[0].frame_data["reason"] == "duplicate_call_id"


def test_normalizer_runs_configured_normalize_hook() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))
    hooks = ActionNormalizeHookPipeline()
    hooks.registry.register_normalize_hook("reject", RejectNormalizeHook())
    hooks.registry.register_global_normalize("reject")

    normalization = ActionCallNormalizer(hooks=hooks).normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments={"text": "done"},
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )

    assert normalization.calls == ()
    assert normalization.results[0].stage is ActionResultStage.NORMALIZE
    assert normalization.results[0].model_feedback == "Rejected during normalize"


def test_normalizer_returns_result_for_unexpected_action_arguments() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="workspace.scan",
                arguments={"path": "."},
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )

    assert normalization.calls == ()
    assert normalization.results[0].status is ActionResultStatus.FAILED
    assert normalization.results[0].stage is ActionResultStage.NORMALIZE
    assert "Unexpected action parameter" in normalization.results[0].model_feedback


def test_normalization_merges_results_by_original_sequence() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments={},
                kind=ToolKind.ACTION,
            ),
            ToolCallRecord(
                id="call_2",
                name="workspace.scan",
                arguments={},
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )
    execution_result = ActionResult.success(
        call_id="call_2",
        invoke_id="invoke_2",
        batch_id="batch_1",
        action_name="workspace.scan",
        sequence=2,
    )

    merged = normalization.merged_results((execution_result,))

    assert [result.call_id for result in merged] == ["call_1", "call_2"]
    assert [result.stage for result in merged] == [
        ActionResultStage.NORMALIZE,
        ActionResultStage.EXECUTE,
    ]


def test_build_execution_batch_from_calls() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))
    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="workspace.scan",
                arguments={},
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )

    preparation = ActionExecutionBuilder().prepare_batch(
        normalization.calls,
        catalog=catalog,
        scope=RunScope(),
        batch_id="batch_1",
    )

    assert preparation.results == ()
    assert preparation.phase_results == ()
    batch = preparation.batch
    assert batch.batch_id == "batch_1"
    assert batch.executions[0].framework.domain == "workspace"
    assert batch.executions[0].framework.timeout_seconds == 30.0


def test_prepare_batch_returns_result_for_duplicate_call_id() -> None:
    preparation = ActionExecutionBuilder().prepare_batch(
        (
            ActionCall("call_1", "core.answer", {}, 1),
            ActionCall("call_1", "workspace.scan", {}, 2),
        ),
        catalog=ActionCatalogLoader().load(Path("tinysoul/action/builtin")),
        scope=RunScope(),
        batch_id="batch_1",
    )

    assert [execution.call.call_id for execution in preparation.batch.executions] == [
        "call_1"
    ]
    assert preparation.results[0].stage is ActionResultStage.PREPARE
    assert preparation.results[0].frame_data["reason"] == "duplicate_call_id"


def test_prepare_batch_returns_result_for_unknown_action() -> None:
    preparation = ActionExecutionBuilder().prepare_batch(
        (
            ActionCall("call_1", "missing.action", {}, 1),
        ),
        catalog=ActionCatalogLoader().load(Path("tinysoul/action/builtin")),
        scope=RunScope(),
        batch_id="batch_1",
    )

    assert preparation.batch.executions == ()
    assert preparation.results[0].stage is ActionResultStage.PREPARE
    assert preparation.results[0].frame_data["reason"] == "unknown_action"


def test_action_batch_rejects_duplicate_call_id() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))
    with pytest.raises(ActionInvariantError, match="Duplicate action call id"):
        ActionBatch(
            batch_id="batch_1",
            executions=(
                ActionExecution(
                    action=catalog.get_action("core.answer"),
                    call=ActionCall("call_1", "core.answer", {}, 1),
                    framework=ActionFramework(
                        invoke_id="invoke_1",
                        batch_id="batch_1",
                        scope=RunScope(),
                        domain="core",
                    ),
                ),
                ActionExecution(
                    action=catalog.get_action("workspace.scan"),
                    call=ActionCall("call_1", "workspace.scan", {}, 2),
                    framework=ActionFramework(
                        invoke_id="invoke_2",
                        batch_id="batch_1",
                        scope=RunScope(),
                        domain="workspace",
                    ),
                ),
            ),
        )


def test_action_batch_rejects_duplicate_sequence() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))
    with pytest.raises(ActionInvariantError, match="Duplicate action sequence"):
        ActionBatch(
            batch_id="batch_1",
            executions=(
                ActionExecution(
                    action=catalog.get_action("core.answer"),
                    call=ActionCall("call_1", "core.answer", {}, 1),
                    framework=ActionFramework(
                        invoke_id="invoke_1",
                        batch_id="batch_1",
                        scope=RunScope(),
                        domain="core",
                    ),
                ),
                ActionExecution(
                    action=catalog.get_action("workspace.scan"),
                    call=ActionCall("call_2", "workspace.scan", {}, 1),
                    framework=ActionFramework(
                        invoke_id="invoke_2",
                        batch_id="batch_1",
                        scope=RunScope(),
                        domain="workspace",
                    ),
                ),
            ),
        )
