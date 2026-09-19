"""Async Action scheduling with joined cancellation and typed execution facts."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from time import monotonic
from tinysoul.infra.concurrency import JoinedOperations

from tinysoul.runtime import (
    RunScope,
    RuntimeException,
    RuntimeTransferInterrupt,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    NullObservationEmitter,
    emit_observation,
)
from tinysoul.kernel.action.runtime_bridge import RuntimeActionBridge

from ..call import ActionBatch, ActionExecution, ExecutionFact, ExecutionState
from ..errors import ActionContractError, ActionInvariantError
from .executor import (
    ActionExecutionCancelled,
    ActionExecutionContext,
    ActionExecutionControl,
    ActionExecutor,
    ExecutorRegistry,
)
from .hooks import ActionExecutionHookPipeline
from ..result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStatus,
    ActionTraceMode,
)
from ..catalog.specs import ActionParallelPolicy


class BatchConcurrencyPlanner:
    """Split executions at serial Action boundaries."""

    def plan(self, batch: ActionBatch) -> tuple[tuple[ActionExecution, ...], ...]:
        groups: list[tuple[ActionExecution, ...]] = []
        parallel: list[ActionExecution] = []
        for execution in batch.executions:
            if execution.action.runtime.parallel_policy is ActionParallelPolicy.ALLOWED:
                parallel.append(execution)
                continue
            if parallel:
                groups.append(tuple(parallel))
                parallel.clear()
            groups.append((execution,))
        if parallel:
            groups.append(tuple(parallel))
        return tuple(groups)


class ActionBatchRunner:
    """Own every task until it settles; execution facts belong to the caller's Trace."""

    def __init__(
        self,
        *,
        executors: ExecutorRegistry,
        hooks: ActionExecutionHookPipeline | None = None,
        planner: BatchConcurrencyPlanner | None = None,
        max_workers: int = 8,
        observations: ObservationEmitter | None = None,
    ) -> None:
        if (
            isinstance(max_workers, bool)
            or not isinstance(max_workers, int)
            or max_workers <= 0
        ):
            raise ActionContractError("max_workers must be positive")
        self._executors = executors
        self._hooks = hooks or ActionExecutionHookPipeline()
        self._planner = planner or BatchConcurrencyPlanner()
        self._max_workers = max_workers
        self._bridge = RuntimeActionBridge()
        self._observations = observations or NullObservationEmitter()

    async def run(
        self,
        batch: ActionBatch,
        context: ActionExecutionContext,
    ) -> tuple[ActionResult, ...]:
        results: list[ActionResult] = []
        scheduled: set[str] = set()
        for execution in batch.executions:
            self._record(context, execution, ExecutionState.REQUESTED)
        try:
            for group in self._planner.plan(batch):
                if context.cancelled is not None and context.cancelled():
                    raise ActionExecutionCancelled("turn_cancelled")
                scheduled.update(item.framework.invoke_id for item in group)
                results.extend(await self._run_group(group, context))
        finally:
            for execution in batch.executions:
                if execution.framework.invoke_id not in scheduled:
                    self._record(context, execution, ExecutionState.NOT_EXECUTED)
        return tuple(sorted(results, key=lambda result: result.sequence))

    async def _run_group(
        self,
        group: tuple[ActionExecution, ...],
        context: ActionExecutionContext,
    ) -> tuple[ActionResult, ...]:
        gate = asyncio.Semaphore(self._max_workers)
        contexts = [
            replace(
                context,
                control=ActionExecutionControl(),
                owner_operations=JoinedOperations(),
            )
            for _ in group
        ]
        tasks = [
            asyncio.create_task(self._limited(execution, owned, gate))
            for execution, owned in zip(group, contexts, strict=True)
        ]
        primary_failure: BaseException | None = None
        try:
            pending = set(tasks)
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=0.05,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # Submission order makes simultaneous failures deterministic.
                for task in tasks:
                    if task in done:
                        task.result()
                if context.cancelled is not None and context.cancelled():
                    raise ActionExecutionCancelled("turn_cancelled")
            return tuple(task.result() for task in tasks)
        except BaseException as exc:
            primary_failure = exc
            raise
        finally:
            for task, owned in zip(tasks, contexts, strict=True):
                if not task.done():
                    owned.control.request_cancel("cancelled")
                    task.cancel()
            joined = asyncio.gather(*tasks, return_exceptions=True)
            late_cancellation: asyncio.CancelledError | None = None
            while not joined.done():
                try:
                    await asyncio.shield(joined)
                except asyncio.CancelledError as exc:
                    # Repeated cancellation cannot detach already-started work.
                    late_cancellation = exc
                    continue
            if primary_failure is None and late_cancellation is not None:
                raise late_cancellation

    async def _limited(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
        gate: asyncio.Semaphore,
    ) -> ActionResult:
        started = False
        settled = False
        try:
            async with gate:
                if context.cancelled is not None and context.cancelled():
                    raise ActionExecutionCancelled("turn_cancelled")
                timeout = execution.framework.timeout_seconds
                execution = replace(
                    execution,
                    framework=replace(
                        execution.framework,
                        deadline=monotonic() + timeout if timeout is not None else None,
                    ),
                )
                context.control.deadline = execution.framework.deadline
                self._record(context, execution, ExecutionState.STARTED)
                started = True
                work = asyncio.create_task(self._run_one(execution, context))
                cancellation: asyncio.CancelledError | None = None
                try:
                    done, _ = await asyncio.wait(
                        (work,),
                        timeout=context.control.remaining_seconds(),
                    )
                    if not done:
                        context.control.request_cancel("timeout")
                        work.cancel()
                except asyncio.CancelledError as exc:
                    cancellation = exc
                    context.control.request_cancel("cancelled")
                    work.cancel()
                # A bounded owner operation may finish after cancellation. Its
                # actual result must reach Trace before cancellation propagates.
                while not work.done():
                    try:
                        await asyncio.shield(work)
                    except asyncio.CancelledError as exc:
                        owner = asyncio.current_task()
                        if owner is not None and owner.cancelling():
                            cancellation = cancellation or exc
                            context.control.request_cancel("cancelled")
                            if not work.done():
                                work.cancel()
                    except Exception:
                        # Retrieve the settled exception below so deadline and
                        # cooperative cancellation share the same classification.
                        if not work.done():
                            raise
                try:
                    result = work.result()
                except (asyncio.CancelledError, ActionExecutionCancelled):
                    if context.control.cancel_reason != "timeout":
                        raise
                    result = self._timeout_result(execution)
                self._record(context, execution, ExecutionState.SETTLED, result)
                settled = True
                if cancellation is not None:
                    raise cancellation
                if context.control.cancel_reason != "timeout":
                    context.owner_operations.check_cancelled()
                return result
        except (asyncio.CancelledError, ActionExecutionCancelled):
            context.control.request_cancel("cancelled")
            if not settled:
                self._record(
                    context,
                    execution,
                    (
                        ExecutionState.CANCELLED
                        if started
                        else ExecutionState.NOT_EXECUTED
                    ),
                )
            raise
        except (RuntimeException, RuntimeTransferInterrupt):
            if not settled:
                self._record(context, execution, ExecutionState.UNKNOWN)
            raise
        except Exception as exc:
            if not settled:
                self._record(context, execution, ExecutionState.UNKNOWN)
            raise self._bridge.from_action_error(exc) from exc

    async def _run_one(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        hook_result = self._hooks.run(execution, context=context)
        if hook_result is None:
            executor = self._executors.get(execution.action.backend.handler)
            result = await self._execute(executor, execution, context)
        else:
            result = hook_result
        if not isinstance(result, ActionResult):
            raise ActionInvariantError(
                "Action executor returned an invalid result object"
            )
        if self._result_mismatch(execution, result):
            raise ActionInvariantError(
                "Action executor returned another invocation's result"
            )
        if self._trace_projection_mismatch(execution, result):
            raise ActionInvariantError(
                "Action executor violated the result trace policy"
            )
        # Already committed owner results remain true after a late deadline.
        return result

    async def _execute(
        self,
        executor: ActionExecutor,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        if context.module_runner is None:
            return await executor.execute(execution, context)

        async def invoke(module_scope: RunScope) -> ActionResult:
            return await executor.execute(
                replace(
                    execution,
                    framework=replace(
                        execution.framework,
                        scope=module_scope,
                    ),
                ),
                context,
            )

        return await context.module_runner.run(
            scope=execution.framework.scope,
            name=execution.framework.invoke_id,
            callback=invoke,
        )

    def _record(
        self,
        context: ActionExecutionContext,
        execution: ActionExecution,
        state: ExecutionState,
        result: ActionResult | None = None,
    ) -> None:
        if context.record_execution is not None:
            context.record_execution(
                ExecutionFact(
                    call=execution.call,
                    framework=execution.framework,
                    state=state,
                    result=result,
                )
            )
        emit_observation(
            self._observations,
            ObservationEvent(
                name="action.execution",
                level=ObservationLevel.VERBOSE,
                source="action.runner",
                scope=execution.framework.scope,
                message="Action execution state changed.",
                payload={
                    "invoke_id": execution.framework.invoke_id,
                    "call_id": execution.call.call_id,
                    "state": state.value,
                },
            ),
        )

    @staticmethod
    def _timeout_result(
        execution: ActionExecution, *, reason: str = "execution_timeout"
    ) -> ActionResult:
        return ActionResult.timeout(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            failure=ActionLocalFailure(
                reason=reason,
                scope="action.timeout",
                disposition=ActionFailureDisposition.RETRY_SAME,
                feedback="Action exceeded its execution deadline.",
            ),
            frame_data={
                "executor_started": True,
                "cancel_reason": "timeout",
                "executor_leaked": False,
                "late_success": False,
                "cancel_requested": True,
            },
        )

    @staticmethod
    def _result_mismatch(execution: ActionExecution, result: ActionResult) -> bool:
        return (
            result.call_id != execution.call.call_id
            or result.invoke_id != execution.framework.invoke_id
            or result.batch_id != execution.framework.batch_id
            or result.action_name != execution.call.action_name
            or result.sequence != execution.call.sequence
            or result.domain != execution.framework.domain
        )

    @staticmethod
    def _trace_projection_mismatch(
        execution: ActionExecution, result: ActionResult
    ) -> bool:
        if result.status is not ActionResultStatus.SUCCESS:
            return False
        return (
            execution.action.runtime.result.trace_mode is ActionTraceMode.FOLDABLE
        ) != (result.trace_projection is not None)
