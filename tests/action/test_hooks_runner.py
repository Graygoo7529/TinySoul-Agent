from __future__ import annotations

from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import cast

import pytest

from tests.action_helpers import FunctionActionExecutor
from tinysoul.action.core.call import ActionCallNormalizer, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.errors import ActionContractError, ActionInvariantError
from tinysoul.action.core.executor import ActionExecutionContext, ExecutorRegistry
from tinysoul.action.core.hooks import (
    ActionExecutionHookPipeline,
    ActionNormalizeHookPipeline,
    HookOutcome,
)
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.action.core.result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
    ActionResultStatus,
    ActionTraceMode,
    ActionTraceProjection,
)
from tinysoul.action.core.runner import ActionBatchRunner
from tinysoul.action.core.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionParallelPolicy,
    ActionResultRuntimeSpec,
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
        return HookOutcome.reject(
            _test_hook_failure(),
            payload={"blocked_resource": "resource_1"},
            frame_data={"policy_revision": 3},
        )


class InvalidOutcomeHook:
    def check(self, execution, context) -> HookOutcome:
        return cast(HookOutcome, None)


class ReservedFrameHook:
    def check(self, execution, context) -> HookOutcome:
        return HookOutcome.reject(
            _test_hook_failure(),
            frame_data={"hook": "spoofed"},
        )


class ExplodingHook:
    def check(self, execution, context) -> HookOutcome:
        raise RuntimeError("boom")


class RuntimeExceptionHook:
    def check(self, execution, context) -> HookOutcome:
        raise RuntimeException(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
            payload={"link": "home:skills/test/ref.md"},
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
            payload={"link": "home:skills/test/ref.md"},
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
            payload={"link": "home:skills/test/ref.md"},
        )


class ProjectionExecutor:
    def execute(self, execution, context) -> ActionResult:
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload={"text": "full"},
            trace_projection=ActionTraceProjection(
                origin_refs=("workspace:a.md", "workspace:b.md"),
                canonical_payload={"links": ["workspace:a.md", "workspace:b.md"]},
            ),
        )


ANSWER_ARGS: JsonObject = {"guide_blocks": [{"text": "answer"}]}


def _test_hook_failure() -> ActionLocalFailure:
    return ActionLocalFailure(
        reason="hook_rejected",
        scope="action.hook",
        disposition=ActionFailureDisposition.CHANGE_REQUEST,
        feedback="Rejected by test hook",
        constraint={"state": "blocked"},
    )


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
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )

    results = ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    )

    assert len(results) == 1
    assert results[0].status is ActionResultStatus.SUCCESS
    assert results[0].call_id == "call_1"
    assert results[0].payload == {"ok": True}


def test_runner_accepts_projection_for_foldable_action() -> None:
    catalog, batch = _single_test_batch(
        _test_action("test.foldable", trace_mode=ActionTraceMode.FOLDABLE)
    )
    executors = ExecutorRegistry()
    executors.register("test.foldable", ProjectionExecutor())

    result = ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    )[0]

    assert result.status is ActionResultStatus.SUCCESS
    assert result.trace_projection is not None
    assert result.trace_projection.origin_refs == (
        "workspace:a.md",
        "workspace:b.md",
    )


def test_runner_rejects_missing_foldable_projection() -> None:
    catalog, batch = _single_test_batch(
        _test_action("test.foldable", trace_mode=ActionTraceMode.FOLDABLE)
    )
    executors = ExecutorRegistry()
    executors.register(
        "test.foldable",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )

    result = ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    )[0]

    assert result.status is ActionResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason == "result_trace_policy_mismatch"


def test_runner_rejects_projection_for_standard_action() -> None:
    catalog, batch = _single_test_batch(_test_action("test.standard"))
    executors = ExecutorRegistry()
    executors.register("test.standard", ProjectionExecutor())

    result = ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    )[0]

    assert result.status is ActionResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason == "result_trace_policy_mismatch"


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
    assert raised.value.payload["link"] == "home:skills/test/ref.md"


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

    executors.register("test.interrupt", FunctionActionExecutor(interrupting))
    executors.register("test.peer", FunctionActionExecutor(cooperative))

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

    executors.register("test.interrupt", FunctionActionExecutor(interrupting))
    executors.register("test.peer", FunctionActionExecutor(blocking))
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

    executors.register("test.interrupt", FunctionActionExecutor(interrupting))
    executors.register("test.peer", FunctionActionExecutor(blocking))
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


def test_runtime_transfer_during_timeout_grace_does_not_wait_for_peer() -> None:
    peer_started = Event()
    release_peer = Event()
    _, batch = _parallel_runtime_batch(interrupt_timeout_seconds=0.01)
    executors = ExecutorRegistry()

    def interrupting(execution, context):
        assert peer_started.wait(1.0)
        sleep(0.02)
        raise RuntimeException(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
        )

    def blocking(execution, context):
        peer_started.set()
        assert release_peer.wait(1.0)
        return {}

    executors.register("test.interrupt", FunctionActionExecutor(interrupting))
    executors.register("test.peer", FunctionActionExecutor(blocking))
    started = monotonic()
    try:
        with pytest.raises(RuntimeException):
            ActionBatchRunner(
                executors=executors,
                cooperative_cancel_grace_seconds=0.05,
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
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )

    assert executors.missing_handlers_for(catalog) == (
        "context.inspect",
        "core.reason",
        "home.prompt_mount.patch",
        "home.prompt_mount.write",
        "home.resource.delete",
        "home.resource.patch",
        "home.resource.read",
        "home.resource.write",
        "home.top.delete",
        "home.top.patch",
        "home.top.search",
        "home.top.write",
        "memory.recall",
        "memory.search",
        "resource.convert_with_markitdown",
        "resource.convert_with_pypdf",
        "script.patch",
        "script.promote",
        "script.rewrite",
        "script.run_bash",
        "script.run_python",
        "script.write",
        "session.inspect",
        "shell.run_bash",
        "shell.run_cmd",
        "shell.run_powershell",
        "supervised_process.apply",
        "supervised_process.discard",
        "supervised_process.read_candidate",
        "supervised_process.stop",
        "supervised_process.wait",
        "web.discover_pages",
        "web.fetch_with_defuddle",
        "web.fetch_with_trafilatura",
        "web.search_by_kimi",
        "workspace.analyze",
        "workspace.delete",
        "workspace.describe",
        "workspace.patch",
        "workspace.read",
        "workspace.restore",
        "workspace.rewrite",
        "workspace.scan",
        "workspace.search_text",
        "workspace.trash.list",
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
    assert results[0].failure is not None
    assert results[0].failure.reason == "executor_result_mismatch"
    mismatch = results[0].frame_data["mismatch"]
    assert isinstance(mismatch, dict)
    assert "call_id" in mismatch


def test_runner_returns_failed_result_when_hook_rejects() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_execution_hook("reject", RejectHook())
    hooks.registry.register_global_execution("reject")

    results = ActionBatchRunner(
        executors=executors,
        hooks=hooks,
    ).run(batch, ActionExecutionContext())

    assert results[0].status is ActionResultStatus.FAILED
    assert results[0].failure is not None
    assert results[0].failure.reason == "hook_rejected"
    assert results[0].failure.scope == "action.hook"
    assert (
        results[0].failure.disposition
        is ActionFailureDisposition.CHANGE_REQUEST
    )
    assert results[0].failure.feedback == "Rejected by test hook"
    assert results[0].failure.constraint == {"state": "blocked"}
    assert results[0].payload == {"blocked_resource": "resource_1"}
    assert results[0].frame_data == {
        "hook": "reject",
        "policy_revision": 3,
    }


def test_hook_outcome_reject_requires_typed_failure() -> None:
    with pytest.raises(ActionInvariantError):
        HookOutcome.reject(cast(ActionLocalFailure, None))


@pytest.mark.parametrize(
    "outcome",
    (
        lambda: HookOutcome(payload={"unexpected": True}),
        lambda: HookOutcome(frame_data={"unexpected": True}),
    ),
)
def test_successful_hook_outcome_cannot_carry_result_data(outcome) -> None:
    with pytest.raises(ActionInvariantError, match="successful HookOutcome"):
        outcome()


@pytest.mark.parametrize(
    "field",
    (
        "hook",
        "failure",
        "reason",
        "scope",
        "disposition",
        "feedback",
        "model_feedback",
        "constraint",
    ),
)
def test_hook_outcome_rejects_reserved_frame_fields(field: str) -> None:
    with pytest.raises(ActionInvariantError):
        HookOutcome.reject(
            _test_hook_failure(),
            frame_data={field: "duplicate"},
        )


def test_hook_outcome_rejects_failure_inside_business_payload() -> None:
    with pytest.raises(ActionInvariantError, match="payload cannot contain failure"):
        HookOutcome.reject(
            _test_hook_failure(),
            payload={"failure": {"reason": "duplicate"}},
        )


def test_runner_returns_local_failure_for_invalid_hook_outcome() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_execution_hook("invalid", InvalidOutcomeHook())
    hooks.registry.register_global_execution("invalid")

    result = ActionBatchRunner(executors=executors, hooks=hooks).run(
        batch,
        ActionExecutionContext(),
    )[0]

    assert result.failure is not None
    assert result.failure.reason == "execution_hook_failed"
    assert result.frame_data == {
        "hook": "invalid",
        "returned_type": "NoneType",
    }


def test_runner_preserves_pipeline_identity_for_reserved_hook_frame() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_execution_hook("reserved", ReservedFrameHook())
    hooks.registry.register_global_execution("reserved")

    result = ActionBatchRunner(executors=executors, hooks=hooks).run(
        batch,
        ActionExecutionContext(),
    )[0]

    assert result.failure is not None
    assert result.failure.reason == "execution_hook_failed"
    assert result.frame_data["hook"] == "reserved"
    assert result.frame_data["error_type"] == "ActionInvariantError"


def test_runner_returns_failed_result_when_hook_is_unknown() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
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
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
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
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
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
        FunctionActionExecutor(lambda execution, context: sleep(0.2) or {}),
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
        FunctionActionExecutor(lambda execution, context: sleep(0.2) or {}),
    )
    executors.register(
        "test.next",
        FunctionActionExecutor(lambda execution, context: {"started": True}),
    )

    results = ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    )

    assert results[0].status is ActionResultStatus.TIMEOUT
    assert results[1].status is ActionResultStatus.FAILED
    assert results[1].failure is not None
    assert results[1].failure.reason == "previous_action_timeout_leak"
    assert results[1].frame_data["blocked_by_invoke_ids"] == [
        results[0].invoke_id
    ]


def _parallel_runtime_batch(
    *,
    interrupt_timeout_seconds: float | None = None,
    peer_timeout_seconds: float | None = None,
):
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(
            _test_action(
                "test.interrupt",
                timeout_seconds=interrupt_timeout_seconds,
            ),
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
    trace_mode: ActionTraceMode = ActionTraceMode.STANDARD,
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
            result=ActionResultRuntimeSpec(trace_mode=trace_mode),
        ),
        backend=ActionBackendSpec(
            kind=ActionBackendKind.NATIVE,
            handler=name,
        ),
    )


def _single_test_batch(action: ActionSpec):
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="test", description="Test actions."),),
        actions=(action,),
    )
    normalization = ActionCallNormalizer().normalize(
        (
            ToolCallRecord(
                id="call_1",
                name=action.name,
                arguments={},
                kind=ToolKind.ACTION,
            ),
        ),
        catalog=catalog,
    )
    return catalog, ActionExecutionBuilder().build_batch(
        normalization.calls,
        catalog=catalog,
        scope=RunScope(),
        batch_id="batch_1",
    )
