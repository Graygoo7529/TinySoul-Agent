from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import cast

import pytest

from tests.action_helpers import FunctionActionExecutor
from tinysoul.action.core.call import ActionCallNormalizer, ActionExecutionBuilder, ExecutionFact, ExecutionState
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
from tinysoul.home.failures import HOME_RUNTIME_COPY_REQUIRED
from tinysoul.llm.failures import LLM_CONTEXT_CAPACITY_EXCEEDED, LLMFailureKind
from tinysoul.llm.runtime_bridge import RuntimeLLMBridge
from tinysoul.runtime import (
    RunFrame,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeTransfer,
    RuntimeTransferInterrupt,
    RuntimeModuleRunner,
    RuntimeTrap,
    SignalBus,
    TrapHandlerRegistry,
    TrapResult,
    TrapSnap,
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
    async def execute(self, execution, context) -> ActionResult:
        return ActionResult.success(
            call_id="other_call",
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
        )


class RuntimeExceptionExecutor:
    async def execute(self, execution, context) -> ActionResult:
        raise RuntimeException(
            reason=HOME_RUNTIME_COPY_REQUIRED,
            message="copy required",
            payload={"link": "home:skills/test/ref.md"},
        )


class ProjectionExecutor:
    async def execute(self, execution, context) -> ActionResult:
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


async def test_runner_returns_action_result_from_executor() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )

    results = (await ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    ))

    assert len(results) == 1
    assert results[0].status is ActionResultStatus.SUCCESS
    assert results[0].call_id == "call_1"
    assert results[0].payload == {"ok": True}


async def test_runner_accepts_projection_for_foldable_action() -> None:
    catalog, batch = _single_test_batch(
        _test_action("test.foldable", trace_mode=ActionTraceMode.FOLDABLE)
    )
    executors = ExecutorRegistry()
    executors.register("test.foldable", ProjectionExecutor())

    result = (await ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    ))[0]

    assert result.status is ActionResultStatus.SUCCESS
    assert result.trace_projection is not None
    assert result.trace_projection.origin_refs == (
        "workspace:a.md",
        "workspace:b.md",
    )


async def test_runner_rejects_missing_foldable_projection() -> None:
    catalog, batch = _single_test_batch(
        _test_action("test.foldable", trace_mode=ActionTraceMode.FOLDABLE)
    )
    executors = ExecutorRegistry()
    executors.register(
        "test.foldable",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )

    with pytest.raises(RuntimeException) as raised:
        await ActionBatchRunner(executors=executors).run(batch, ActionExecutionContext())
    assert raised.value.payload["kind"] == "action.internal_failure"


async def test_runner_rejects_projection_for_standard_action() -> None:
    catalog, batch = _single_test_batch(_test_action("test.standard"))
    executors = ExecutorRegistry()
    executors.register("test.standard", ProjectionExecutor())

    with pytest.raises(RuntimeException) as raised:
        await ActionBatchRunner(executors=executors).run(batch, ActionExecutionContext())
    assert raised.value.payload["kind"] == "action.internal_failure"


async def test_runner_allows_runtime_exception_to_reach_trap() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register("core.answer", RuntimeExceptionExecutor())

    with pytest.raises(RuntimeException) as raised:
        (await ActionBatchRunner(executors=executors).run(
            batch,
            ActionExecutionContext(),
        ))

    assert raised.value.reason == HOME_RUNTIME_COPY_REQUIRED
    assert raised.value.payload["link"] == "home:skills/test/ref.md"


async def test_capacity_retry_replays_only_interrupted_action() -> None:
    peer_committed = Event()
    _, batch = _parallel_runtime_batch()
    attempts: list[str] = []
    commits: list[str] = []

    def recovering(execution, context):
        attempts.append(execution.framework.invoke_id)
        if len(attempts) == 1:
            assert peer_committed.wait(1.0)
            raise RuntimeLLMBridge().from_failure(
                LLMFailureKind.MODEL_CONTEXT_PRESSURE,
                message="Capacity recovery required.",
            )
        return {"recovered": True}

    def committing(execution, context):
        commits.append(execution.call.call_id)
        peer_committed.set()
        return {"committed": True}

    class RecoveryHandler:
        def handle(self, snap: TrapSnap) -> TrapResult:
            frame = snap.scope.current()
            assert frame is not None and frame.level is RunLevel.MODULE
            return TrapResult(transfer=RuntimeTransfer.retry(frame))

    registry = TrapHandlerRegistry()
    registry.register(LLM_CONTEXT_CAPACITY_EXCEEDED, RecoveryHandler())
    executors = ExecutorRegistry()
    executors.register("test.interrupt", FunctionActionExecutor(recovering))
    executors.register("test.peer", FunctionActionExecutor(committing))
    results = (await ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(module_runner=RuntimeModuleRunner(
            trap=RuntimeTrap(registry=registry), bus=SignalBus(),
        )),
    ))

    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert commits == ["call_2"]
    assert len(results) == 2
    assert all(result.status is ActionResultStatus.SUCCESS for result in results)


async def test_runtime_transfer_cancels_parallel_cooperative_action() -> None:
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
        (await ActionBatchRunner(
            executors=executors,
        ).run(batch, ActionExecutionContext()))

    assert cancel_seen.is_set()


@pytest.mark.parametrize("peer_timeout", [None, 0.01])
async def test_runtime_transfer_joins_owner_and_retains_commit(peer_timeout) -> None:
    peer_started = Event()
    release_peer = Event()
    committed = Event()
    _, batch = _parallel_runtime_batch(peer_timeout_seconds=peer_timeout)
    executors = ExecutorRegistry()
    failure = RuntimeException(reason=HOME_RUNTIME_COPY_REQUIRED, message="copy required")
    facts: list[ExecutionFact] = []

    def interrupting(execution, context):
        assert peer_started.wait(2.0)
        raise failure

    def writing(execution, context):
        peer_started.set()
        assert release_peer.wait(2.0)
        committed.set()
        return {"committed": True}

    executors.register("test.interrupt", FunctionActionExecutor(interrupting))
    executors.register("test.peer", FunctionActionExecutor(writing))
    running = asyncio.create_task(ActionBatchRunner(executors=executors).run(
        batch, ActionExecutionContext(record_execution=facts.append),
    ))
    try:
        async with asyncio.timeout(2.0):
            while not any(fact.state is ExecutionState.UNKNOWN for fact in facts):
                await asyncio.sleep(0)
        assert not running.done()
        release_peer.set()
        with pytest.raises(RuntimeException) as raised:
            await running
        assert raised.value is failure
        assert committed.is_set()
        peer = [fact for fact in facts if fact.call.call_id == "call_2"][-1]
        assert peer.state is ExecutionState.SETTLED
        assert peer.result is not None and peer.result.payload == {"committed": True}
    finally:
        release_peer.set()
        await asyncio.gather(running, return_exceptions=True)


async def test_cancel_interrupts_async_executor_and_preserves_prior_success() -> None:
    _, batch = _parallel_runtime_batch()
    entered = asyncio.Event()
    closed = asyncio.Event()
    facts: list[ExecutionFact] = []

    class WaitingExecutor:
        async def execute(self, execution, context) -> ActionResult:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
            raise AssertionError("unreachable")

    executors = ExecutorRegistry()
    executors.register("test.interrupt", FunctionActionExecutor(
        lambda execution, context: {"committed": True},
    ))
    executors.register("test.peer", WaitingExecutor())
    running = asyncio.create_task(ActionBatchRunner(executors=executors).run(
        batch, ActionExecutionContext(record_execution=facts.append),
    ))
    async with asyncio.timeout(2.0):
        await entered.wait()
        while not any(fact.state is ExecutionState.SETTLED for fact in facts):
            await asyncio.sleep(0)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    assert closed.is_set()
    assert facts[-1].state is ExecutionState.CANCELLED
    assert any(fact.result is not None and fact.result.payload == {"committed": True}
               for fact in facts)


async def test_repeated_cancellation_joins_owner_before_propagating() -> None:
    _, batch = _single_test_batch(_test_action("test.write"))
    started = Event()
    release = Event()
    facts: list[ExecutionFact] = []

    def write(execution, context):
        started.set()
        assert release.wait(2.0)
        return {"committed": True}

    executors = ExecutorRegistry()
    executors.register("test.write", FunctionActionExecutor(write))
    running = asyncio.create_task(ActionBatchRunner(executors=executors).run(
        batch, ActionExecutionContext(record_execution=facts.append),
    ))
    try:
        async with asyncio.timeout(2.0):
            while not started.is_set():
                await asyncio.sleep(0)
            running.cancel()
            await asyncio.sleep(0)
            running.cancel()
            assert not running.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await running
        assert facts[-1].state is ExecutionState.SETTLED
        assert facts[-1].result is not None
        assert facts[-1].result.payload == {"committed": True}
    finally:
        release.set()
        await asyncio.gather(running, return_exceptions=True)


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

    missing = executors.missing_handlers_for(catalog)
    assert "core.answer" not in missing
    assert "home.resource.read" in missing
    assert len(missing) == len(set(missing))
    with pytest.raises(ActionContractError, match="home.resource.read"):
        executors.validate_catalog(catalog)


async def test_runner_rejects_mismatched_executor_result_at_module_boundary() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register("core.answer", MismatchedExecutor())

    with pytest.raises(RuntimeException) as raised:
        await ActionBatchRunner(executors=executors).run(batch, ActionExecutionContext())
    assert raised.value.payload["kind"] == "action.internal_failure"


async def test_runner_returns_failed_result_when_hook_rejects() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_execution_hook("reject", RejectHook())
    hooks.registry.register_global_execution("reject")

    results = (await ActionBatchRunner(
        executors=executors,
        hooks=hooks,
    ).run(batch, ActionExecutionContext()))

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


async def test_runner_returns_local_failure_for_invalid_hook_outcome() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_execution_hook("invalid", InvalidOutcomeHook())
    hooks.registry.register_global_execution("invalid")

    result = (await ActionBatchRunner(executors=executors, hooks=hooks).run(
        batch,
        ActionExecutionContext(),
    ))[0]

    assert result.failure is not None
    assert result.failure.reason == "execution_hook_failed"
    assert result.frame_data == {
        "hook": "invalid",
        "returned_type": "NoneType",
    }


async def test_runner_preserves_pipeline_identity_for_reserved_hook_frame() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_execution_hook("reserved", ReservedFrameHook())
    hooks.registry.register_global_execution("reserved")

    result = (await ActionBatchRunner(executors=executors, hooks=hooks).run(
        batch,
        ActionExecutionContext(),
    ))[0]

    assert result.failure is not None
    assert result.failure.reason == "execution_hook_failed"
    assert result.frame_data["hook"] == "reserved"
    assert result.frame_data["error_type"] == "ActionInvariantError"


async def test_runner_returns_failed_result_when_hook_is_unknown() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_global_execution("missing")

    results = (await ActionBatchRunner(
        executors=executors,
        hooks=hooks,
    ).run(batch, ActionExecutionContext()))

    assert results[0].status is ActionResultStatus.FAILED
    assert results[0].stage is ActionResultStage.HOOK
    assert results[0].frame_data["hook"] == "missing"


async def test_runner_returns_failed_result_when_hook_raises() -> None:
    catalog, batch = _batch_for("core.answer", ANSWER_ARGS)
    executors = ExecutorRegistry()
    executors.register(
        "core.answer",
        FunctionActionExecutor(lambda execution, context: {"ok": True}),
    )
    hooks = ActionExecutionHookPipeline()
    hooks.registry.register_execution_hook("explode", ExplodingHook())
    hooks.registry.register_global_execution("explode")

    results = (await ActionBatchRunner(
        executors=executors,
        hooks=hooks,
    ).run(batch, ActionExecutionContext()))

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
async def test_runner_propagates_runtime_control_from_execution_hook(
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
        (await ActionBatchRunner(
            executors=executors,
            hooks=hooks,
        ).run(batch, ActionExecutionContext()))


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


async def test_runner_retains_committed_owner_result_after_deadline() -> None:
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

    results = (await ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    ))

    assert results[0].status is ActionResultStatus.SUCCESS


async def test_runner_joins_late_owner_before_starting_next_group() -> None:
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

    results = (await ActionBatchRunner(executors=executors).run(
        batch,
        ActionExecutionContext(),
    ))

    assert all(result.status is ActionResultStatus.SUCCESS for result in results)
    assert results[1].payload == {"started": True}


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
