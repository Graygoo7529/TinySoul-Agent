from __future__ import annotations

from pathlib import Path

from tinysoul.action.backends.native import NativeFunctionExecutor
from tinysoul.action.core.call import ActionCallNormalizer, ActionExecutionBuilder
from tinysoul.action.core.executor import ActionExecutionContext, ExecutorRegistry
from tinysoul.action.core.hooks import ActionHookPipeline, HookOutcome
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.action.core.result import ActionResultStatus
from tinysoul.action.core.runner import ActionBatchRunner
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import RunScope


class RejectHook:
    def check(self, execution, context) -> HookOutcome:
        return HookOutcome.failed("Rejected by test hook")


def _batch_for(action_name: str, arguments: dict[str, object]):
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))
    calls = ActionCallNormalizer().normalize(
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
        calls,
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
