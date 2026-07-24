from __future__ import annotations

from pathlib import Path
from typing import cast

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
from tinysoul.action.core.result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
    ActionResultStatus,
)
from tinysoul.infra.json import JsonObject
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RunScope


class RejectNormalizeHook:
    def check(self, item) -> HookOutcome:
        return HookOutcome.reject(
            ActionLocalFailure(
                reason="hook_rejected",
                scope="action.hook",
                disposition=ActionFailureDisposition.CHANGE_REQUEST,
                feedback="Rejected during normalize",
            ),
            payload={"invalid_fields": ["guide_blocks"]},
            frame_data={"rule_revision": 2},
        )


class InvalidNormalizeHook:
    def check(self, item) -> HookOutcome:
        return cast(HookOutcome, None)


ANSWER_ARGS: JsonObject = {"guide_blocks": [{"text": "answer"}]}


def test_normalize_tool_calls_to_action_calls() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
    tool_calls = (
        ToolCallRecord(
            id="call_1",
            name="core.answer",
            arguments=ANSWER_ARGS,
            kind=ToolKind.ACTION,
        ),
    )

    normalization = ActionCallNormalizer().normalize(tool_calls, catalog=catalog)
    calls = normalization.calls

    assert len(calls) == 1
    assert calls[0].action_name == "core.answer"
    assert calls[0].call_id == "call_1"
    assert calls[0].sequence == 1
    assert calls[0].params == ANSWER_ARGS
    assert normalization.results == ()


def test_normalizer_returns_result_for_non_action_tool_call() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments=ANSWER_ARGS,
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
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

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
    assert normalization.results[0].failure is not None
    assert "Missing required action parameter" in normalization.results[0].failure.feedback


def test_normalizer_returns_result_for_duplicate_call_id() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments=ANSWER_ARGS,
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
    assert normalization.results[0].failure is not None
    assert normalization.results[0].failure.reason == "duplicate_call_id"


def test_normalizer_runs_configured_normalize_hook() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
    hooks = ActionNormalizeHookPipeline()
    hooks.registry.register_normalize_hook("reject", RejectNormalizeHook())
    hooks.registry.register_global_normalize("reject")

    normalization = ActionCallNormalizer(hooks=hooks).normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments=ANSWER_ARGS,
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )

    assert normalization.calls == ()
    assert normalization.results[0].stage is ActionResultStage.NORMALIZE
    assert normalization.results[0].failure is not None
    assert normalization.results[0].failure.feedback == "Rejected during normalize"
    assert normalization.results[0].payload == {
        "invalid_fields": ["guide_blocks"]
    }
    assert normalization.results[0].frame_data == {
        "hook": "reject",
        "rule_revision": 2,
    }


def test_normalizer_returns_local_failure_for_invalid_hook_outcome() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
    hooks = ActionNormalizeHookPipeline()
    hooks.registry.register_normalize_hook("invalid", InvalidNormalizeHook())
    hooks.registry.register_global_normalize("invalid")

    normalization = ActionCallNormalizer(hooks=hooks).normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="core.answer",
                arguments=ANSWER_ARGS,
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )

    result = normalization.results[0]
    assert result.failure is not None
    assert result.failure.reason == "normalize_hook_failed"
    assert result.frame_data == {
        "hook": "invalid",
        "returned_type": "NoneType",
    }


def test_normalizer_returns_result_for_unexpected_action_arguments() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

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
    assert normalization.results[0].failure is not None
    assert "Unexpected action parameter" in normalization.results[0].failure.feedback


def test_normalization_merges_results_by_original_sequence() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

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
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
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


@pytest.mark.parametrize("action_name", ["workspace.write", "workspace.rewrite"])
def test_workspace_llm_edit_batch_uses_action_timeout(action_name: str) -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
    preparation = ActionExecutionBuilder().prepare_batch(
        (
            ActionCall(
                "call_1",
                action_name,
                {
                    "target_link": "workspace:docs/plan.md",
                    "instruction": "Improve the document.",
                },
                1,
            ),
        ),
        catalog=catalog,
        scope=RunScope(),
        batch_id="batch_1",
    )

    assert preparation.results == ()
    assert preparation.phase_results == ()
    execution = preparation.batch.executions[0]
    assert execution.framework.domain == "workspace"
    assert execution.framework.timeout_seconds == 90.0


def test_prepare_batch_returns_result_for_duplicate_call_id() -> None:
    preparation = ActionExecutionBuilder().prepare_batch(
        (
            ActionCall("call_1", "core.answer", {}, 1),
            ActionCall("call_1", "workspace.scan", {}, 2),
        ),
        catalog=ActionCatalogLoader().load(Path("tinysoul/action/catalog")),
        scope=RunScope(),
        batch_id="batch_1",
    )

    assert [execution.call.call_id for execution in preparation.batch.executions] == [
        "call_1"
    ]
    assert preparation.results[0].stage is ActionResultStage.PREPARE
    assert preparation.results[0].failure is not None
    assert preparation.results[0].failure.reason == "duplicate_call_id"


def test_prepare_batch_returns_result_for_unknown_action() -> None:
    preparation = ActionExecutionBuilder().prepare_batch(
        (
            ActionCall("call_1", "missing.action", {}, 1),
        ),
        catalog=ActionCatalogLoader().load(Path("tinysoul/action/catalog")),
        scope=RunScope(),
        batch_id="batch_1",
    )

    assert preparation.batch.executions == ()
    assert preparation.results[0].stage is ActionResultStage.PREPARE
    assert preparation.results[0].failure is not None
    assert preparation.results[0].failure.reason == "unknown_action"


def test_action_batch_rejects_duplicate_call_id() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
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
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
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
