from __future__ import annotations

from pathlib import Path
from time import sleep

from tinysoul.action.backends.native import NativeFunctionExecutor
from tinysoul.action.core.call import ActionCallNormalizer, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.executor import ActionExecutionContext, ExecutorRegistry
from tinysoul.action.core.hooks import ActionHookPipeline, HookOutcome
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.action.core.result import ActionResultStage, ActionResultStatus
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
from tinysoul.runtime import RunScope


class RejectHook:
    def check(self, execution, context) -> HookOutcome:
        return HookOutcome.failed("Rejected by test hook")


class ExplodingHook:
    def check(self, execution, context) -> HookOutcome:
        raise RuntimeError("boom")


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
    catalog, batch = _batch_for("core.answer", {"text": "hello"})
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        NativeFunctionExecutor(lambda execution, context: {"ok": True}),
    )

    results = ActionBatchRunner(catalog=catalog, executors=executors).run(
        batch,
        ActionExecutionContext(),
    )

    assert len(results) == 1
    assert results[0].status is ActionResultStatus.SUCCESS
    assert results[0].call_id == "call_1"
    assert results[0].payload == {"ok": True}


def test_runner_returns_failed_result_when_hook_rejects() -> None:
    catalog, batch = _batch_for("core.answer", {"text": "hello"})
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        NativeFunctionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionHookPipeline()
    hooks.registry.register_hook("reject", RejectHook())
    hooks.registry.register_global("reject")

    results = ActionBatchRunner(
        catalog=catalog,
        executors=executors,
        hooks=hooks,
    ).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.FAILED
    assert results[0].model_feedback == "Rejected by test hook"


def test_runner_returns_failed_result_when_hook_is_unknown() -> None:
    catalog, batch = _batch_for("core.answer", {"text": "hello"})
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        NativeFunctionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionHookPipeline()
    hooks.registry.register_global("missing")

    results = ActionBatchRunner(
        catalog=catalog,
        executors=executors,
        hooks=hooks,
    ).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.FAILED
    assert results[0].stage is ActionResultStage.HOOK
    assert results[0].frame_data["hook"] == "missing"


def test_runner_returns_failed_result_when_hook_raises() -> None:
    catalog, batch = _batch_for("core.answer", {"text": "hello"})
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        NativeFunctionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionHookPipeline()
    hooks.registry.register_hook("explode", ExplodingHook())
    hooks.registry.register_global("explode")

    results = ActionBatchRunner(
        catalog=catalog,
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

    results = ActionBatchRunner(catalog=catalog, executors=executors).run(
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

    results = ActionBatchRunner(catalog=catalog, executors=executors).run(
        batch,
        ActionExecutionContext(),
    )

    assert results[0].status is ActionResultStatus.TIMEOUT
    assert results[1].status is ActionResultStatus.FAILED
    assert results[1].frame_data["reason"] == "previous_action_timeout_leak"
