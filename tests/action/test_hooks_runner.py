from __future__ import annotations

from pathlib import Path
from time import sleep

import pytest

from tinysoul.action.backends.native import NativeFunctionExecutor
from tinysoul.action.core.call import ActionCallNormalizer, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.errors import ActionContractError
from tinysoul.action.core.executor import ActionExecutionContext, ExecutorRegistry
from tinysoul.action.core.hooks import ActionExecutionHookPipeline, HookOutcome
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.action.core.result import ActionResult, ActionResultStage, ActionResultStatus
from tinysoul.action.core.runner import ActionBatchRunner
from tinysoul.action.core.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionParallelPolicy,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.infra.json import JsonObject
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import HOME_RUNTIME_COPY_REQUIRED, RunScope, RuntimeException


class RejectHook:
    def check(self, execution, context) -> HookOutcome:
        return HookOutcome.failed("Rejected by test hook")


class ExplodingHook:
    def check(self, execution, context) -> HookOutcome:
        raise RuntimeError("boom")


class MismatchedExecutor:
    def execute(self, execution, context) -> ActionResult:
        return ActionResult.success(
            call_id="other_call",
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
        )


class RuntimeExceptionExecutor:
    def execute(self, execution, context) -> ActionResult:
        raise RuntimeException(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
            payload={"link": "home:how/test/ref.md"},
        )


ANSWER_ARGS: JsonObject = {"guide_blocks": [{"text": "answer"}]}


def _batch_for(action_name: str, arguments: JsonObject):
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))
    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name=action_name,
                arguments=arguments,
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )
    batch = ActionExecutionBuilder().build_batch(
        normalization.calls,
        catalog=catalog,
        scope=RunScope(),
        batch_id="batch_1",
    )
    return catalog, batch


def test_runner_returns_action_result_from_executor() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "llm_step.answer",
        NativeFunctionExecutor(lambda execution, context: {"ok": True}),
    )

    results = ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    )

    assert len(results) == 1
    assert results[0].status is ActionResultStatus.SUCCESS
    assert results[0].call_id == "call_1"
    assert results[0].payload == {"ok": True}


def test_runner_allows_runtime_exception_to_reach_trap() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register("llm_step.answer", RuntimeExceptionExecutor())

    with pytest.raises(RuntimeException) as raised:
        ActionBatchRunner(executors=executors).run(
            batch,
            ActionExecutionContext(),
        )

    assert raised.value.reason == HOME_RUNTIME_COPY_REQUIRED
    assert raised.value.payload["link"] == "home:how/test/ref.md"


def test_runner_rejects_invalid_max_workers() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    with pytest.raises(ActionContractError, match="max_workers"):
        ActionBatchRunner(
            executors=ExecutorRegistry(),
            max_workers=0,
        )


def test_executor_registry_validates_catalog_handlers() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))
    executors = ExecutorRegistry()
    executors.register("llm_step.answer", NativeFunctionExecutor(lambda execution, context: {"ok": True}))

    assert executors.missing_handlers_for(catalog) == (
        "home.resource.read",
        "llm_step.context_task",
        "workspace.delete",
        "workspace.describe",
        "workspace.patch",
        "workspace.scan",
        "workspace.write",
    )
    with pytest.raises(ActionContractError, match="home.resource.read"):
        executors.validate_catalog(catalog)


def test_runner_returns_failed_result_for_mismatched_executor_result() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register("llm_step.answer", MismatchedExecutor())

    results = ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    )

    assert results[0].status is ActionResultStatus.FAILED
    assert results[0].stage is ActionResultStage.EXECUTE
    assert results[0].frame_data["reason"] == "executor_result_mismatch"
    mismatch = results[0].frame_data["mismatch"]
    assert isinstance(mismatch, dict)
    assert "call_id" in mismatch


def test_runner_returns_failed_result_when_hook_rejects() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "llm_step.answer",
        NativeFunctionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_execution_hook("reject", RejectHook())
    hooks.registry.register_global_execution("reject")

    results = ActionBatchRunner(
        executors=executors,
        hooks=hooks,
    ).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.FAILED
    assert results[0].model_feedback == "Rejected by test hook"


def test_runner_returns_failed_result_when_hook_is_unknown() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "llm_step.answer",
        NativeFunctionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_global_execution("missing")

    results = ActionBatchRunner(
        executors=executors,
        hooks=hooks,
    ).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.FAILED
    assert results[0].stage is ActionResultStage.HOOK
    assert results[0].frame_data["hook"] == "missing"


def test_runner_returns_failed_result_when_hook_raises() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "llm_step.answer",
        NativeFunctionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_execution_hook("explode", ExplodingHook())
    hooks.registry.register_global_execution("explode")

    results = ActionBatchRunner(
        executors=executors,
        hooks=hooks,
    ).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.FAILED
    assert results[0].stage is ActionResultStage.HOOK
    assert results[0].frame_data["error_type"] == "RuntimeError"


def test_runner_returns_timeout_for_blocked_execution() -> None:
    catalog = ActionCatalog(
        domains=(
            ActionDomainSpec(
                name="test",
                description="Test actions.",
            ),
        ),
        actions=(
            ActionSpec(
                name="test.slow",
                domain="test",
                tool=ActionToolSpec(
                    name="test.slow",
                    description="Slow action.",
                    schema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                ),
                semantic=ActionSemanticSpec(),
                runtime=ActionRuntimeSpec(
                    timeout_seconds=0.01,
                    parallel_policy=ActionParallelPolicy.ALLOWED,
                ),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler="test.slow",
                ),
            ),
        ),
    )
    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="test.slow",
                arguments={},
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )
    batch = ActionExecutionBuilder().build_batch(
        normalization.calls,
        catalog=catalog,
        scope=RunScope(),
        batch_id="batch_1",
    )
    executors = ExecutorRegistry()
    executors.register(
        "test.slow",
        NativeFunctionExecutor(lambda execution, context: sleep(0.2) or {}),
    )

    results = ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    )

    assert results[0].status is ActionResultStatus.TIMEOUT


def test_runner_blocks_later_groups_after_timeout_leak() -> None:
    catalog = ActionCatalog(
        domains=(
            ActionDomainSpec(
                name="test",
                description="Test actions.",
            ),
        ),
        actions=(
            ActionSpec(
                name="test.slow",
                domain="test",
                tool=ActionToolSpec(
                    name="test.slow",
                    description="Slow action.",
                    schema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                ),
                semantic=ActionSemanticSpec(),
                runtime=ActionRuntimeSpec(
                    timeout_seconds=0.01,
                    parallel_policy=ActionParallelPolicy.SERIAL,
                ),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler="test.slow",
                ),
            ),
            ActionSpec(
                name="test.next",
                domain="test",
                tool=ActionToolSpec(
                    name="test.next",
                    description="Next action.",
                    schema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                ),
                semantic=ActionSemanticSpec(),
                runtime=ActionRuntimeSpec(
                    parallel_policy=ActionParallelPolicy.SERIAL,
                ),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.NATIVE,
                    handler="test.next",
                ),
            ),
        ),
    )
    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name="test.slow",
                arguments={},
                kind=ToolKind.ACTION,
            ),
            ToolCallRecord(
                id="call_2",
                name="test.next",
                arguments={},
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )
    batch = ActionExecutionBuilder().build_batch(
        normalization.calls,
        catalog=catalog,
        scope=RunScope(),
        batch_id="batch_1",
    )
    executors = ExecutorRegistry()
    executors.register(
        "test.slow",
        NativeFunctionExecutor(lambda execution, context: sleep(0.2) or {}),
    )
    executors.register(
        "test.next",
        NativeFunctionExecutor(lambda execution, context: {"started": True}),
    )

    results = ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    )

    assert results[0].status is ActionResultStatus.TIMEOUT
    assert results[1].status is ActionResultStatus.FAILED
    assert results[1].frame_data["reason"] == "previous_action_timeout_leak"
    assert results[1].frame_data["blocked_by_invoke_ids"] == [
        results[0].invoke_id
    ]
