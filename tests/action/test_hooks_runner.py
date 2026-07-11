from __future__ import annotations

from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest

from tinysoul.action.backends.native import NativeFunctionExecutor
from tinysoul.action.core.call import ActionCallNormalizer, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.errors import ActionContractError
from tinysoul.action.core.executor import ActionExecutionContext, ExecutorRegistry
from tinysoul.action.core.hooks import (
    ActionExecutionHookPipeline,
    ActionNormalizeHookPipeline,
    HookOutcome,
)
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
from tinysoul.runtime import (
    HOME_RUNTIME_COPY_REQUIRED,
    RunFrame,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeTransfer,
    RuntimeTransferInterrupt,
)


class RejectHook:
    def check(self, execution, context) -> HookOutcome:
        return HookOutcome.failed("Rejected by test hook")


class ExplodingHook:
    def check(self, execution, context) -> HookOutcome:
        raise RuntimeError("boom")


class RuntimeExceptionHook:
    def check(self, execution, context) -> HookOutcome:
        raise RuntimeException(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
            payload={"link": "home:how/test/ref.md"},
        )


class RuntimeTransferHook:
    def check(self, execution, context) -> HookOutcome:
        raise RuntimeTransferInterrupt(
            RuntimeTransfer.retry(RunFrame(RunLevel.MODULE, "hook"))
        )


class RuntimeNormalizeHook:
    def check(self, item) -> HookOutcome:
        raise RuntimeException(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
            payload={"link": "home:how/test/ref.md"},
        )


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
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
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
        "core.answer",
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
    executors.register("core.answer", RuntimeExceptionExecutor())

    with pytest.raises(RuntimeException) as raised:
        ActionBatchRunner(executors=executors).run(
            batch,
            ActionExecutionContext(),
        )

    assert raised.value.reason == HOME_RUNTIME_COPY_REQUIRED
    assert raised.value.payload["link"] == "home:how/test/ref.md"


def test_runtime_transfer_cancels_parallel_cooperative_action() -> None:
    peer_started = Event()
    cancel_seen = Event()
    catalog, batch = _parallel_runtime_batch()
    executors = ExecutorRegistry()

    def interrupting(execution, context):
        assert peer_started.wait(1.0)
        raise RuntimeException(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
        )

    def cooperative(execution, context):
        peer_started.set()
        while not context.control.is_cancelled():
            sleep(0.001)
        cancel_seen.set()
        context.control.check_cancelled()
        return {}

    executors.register("test.interrupt", NativeFunctionExecutor(interrupting))
    executors.register("test.peer", NativeFunctionExecutor(cooperative))

    with pytest.raises(RuntimeException):
        ActionBatchRunner(
            executors=executors,
            cooperative_cancel_grace_seconds=0.2,
        ).run(batch, ActionExecutionContext())

    assert cancel_seen.is_set()


def test_runtime_transfer_does_not_wait_for_non_cooperative_native_action() -> None:
    peer_started = Event()
    release_peer = Event()
    catalog, batch = _parallel_runtime_batch()
    executors = ExecutorRegistry()

    def interrupting(execution, context):
        assert peer_started.wait(1.0)
        raise RuntimeException(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
        )

    def blocking(execution, context):
        peer_started.set()
        assert release_peer.wait(1.0)
        return {}

    executors.register("test.interrupt", NativeFunctionExecutor(interrupting))
    executors.register("test.peer", NativeFunctionExecutor(blocking))
    started = monotonic()
    try:
        with pytest.raises(RuntimeException):
            ActionBatchRunner(
                executors=executors,
                cooperative_cancel_grace_seconds=0.01,
            ).run(batch, ActionExecutionContext())
        elapsed = monotonic() - started
    finally:
        release_peer.set()

    assert elapsed < 0.5


def test_runtime_transfer_preserves_prior_timeout_leak_shutdown_policy() -> None:
    peer_started = Event()
    release_peer = Event()
    _, batch = _parallel_runtime_batch(peer_timeout_seconds=0.02)
    executors = ExecutorRegistry()

    def interrupting(execution, context):
        assert peer_started.wait(1.0)
        sleep(0.08)
        raise RuntimeException(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
        )

    def blocking(execution, context):
        peer_started.set()
        assert release_peer.wait(1.0)
        return {}

    executors.register("test.interrupt", NativeFunctionExecutor(interrupting))
    executors.register("test.peer", NativeFunctionExecutor(blocking))
    started = monotonic()
    try:
        with pytest.raises(RuntimeException):
            ActionBatchRunner(
                executors=executors,
                cooperative_cancel_grace_seconds=0.005,
            ).run(batch, ActionExecutionContext())
        elapsed = monotonic() - started
    finally:
        release_peer.set()

    assert elapsed < 0.5


def test_runner_rejects_invalid_max_workers() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

    with pytest.raises(ActionContractError, match="max_workers"):
        ActionBatchRunner(
            executors=ExecutorRegistry(),
            max_workers=0,
        )


def test_executor_registry_validates_catalog_handlers() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
    executors = ExecutorRegistry()
    executors.register("core.answer", NativeFunctionExecutor(lambda execution, context: {"ok": True}))

    assert executors.missing_handlers_for(catalog) == (
        "context.trace.fold",
        "context.trace.inspect",
        "context.trace.recall",
        "core.reason",
        "home.resource.read",
        "session.history.inspect",
        "session.history.recall",
        "workspace.delete",
        "workspace.describe",
        "workspace.patch",
        "workspace.restore",
        "workspace.rewrite",
        "workspace.scan",
        "workspace.write",
    )
    with pytest.raises(ActionContractError, match="home.resource.read"):
        executors.validate_catalog(catalog)


def test_runner_returns_failed_result_for_mismatched_executor_result() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register("core.answer", MismatchedExecutor())

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
        "core.answer",
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
        "core.answer",
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
        "core.answer",
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


@pytest.mark.parametrize(
    ("hook", "error_type"),
    (
        (RuntimeExceptionHook(), RuntimeException),
        (RuntimeTransferHook(), RuntimeTransferInterrupt),
    ),
)
def test_runner_propagates_runtime_control_from_execution_hook(
    hook,
    error_type,
) -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        NativeFunctionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_execution_hook("runtime", hook)
    hooks.registry.register_global_execution("runtime")

    with pytest.raises(error_type):
        ActionBatchRunner(
            executors=executors,
            hooks=hooks,
        ).run(batch, ActionExecutionContext())


def test_normalizer_propagates_runtime_exception_from_hook() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
    hooks = ActionNormalizeHookPipeline()
    hooks.registry.register_normalize_hook("runtime", RuntimeNormalizeHook())
    hooks.registry.register_global_normalize("runtime")

    with pytest.raises(RuntimeException):
        ActionCallNormalizer(hooks).normalize(
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


def _parallel_runtime_batch(*, peer_timeout_seconds: float | None = None):
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _test_action("test.interrupt"),
            _test_action("test.peer", timeout_seconds=peer_timeout_seconds),
        ),
    )
    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord("call_1", "test.interrupt", {}, ToolKind.ACTION),
            ToolCallRecord("call_2", "test.peer", {}, ToolKind.ACTION),
        ),
        catalog=catalog,
    )
    return catalog, ActionExecutionBuilder().build_batch(
        normalization.calls,
        catalog=catalog,
        scope=RunScope(),
        batch_id="batch_runtime",
    )


def _test_action(
    name: str,
    *,
    timeout_seconds: float | None = None,
) -> ActionSpec:
    return ActionSpec(
        name=name,
        domain="test",
        tool=ActionToolSpec(
            name=name,
            description="Test action.",
            schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        ),
        semantic=ActionSemanticSpec(),
        runtime=ActionRuntimeSpec(
            timeout_seconds=timeout_seconds,
            parallel_policy=ActionParallelPolicy.ALLOWED,
        ),
        backend=ActionBackendSpec(
            kind=ActionBackendKind.NATIVE,
            handler=name,
        ),
    )
