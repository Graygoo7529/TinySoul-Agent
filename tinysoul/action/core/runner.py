"""Async Action scheduling with joined cancellation and typed execution facts."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from time import monotonic
from typing import cast
from tinysoul.infra.concurrency import JoinedOperations

from tinysoul.runtime import RunScope, RuntimeException, RuntimeTransferInterrupt, ObservationEmitter
from tinysoul.action.runtime_bridge import RuntimeActionBridge

from .call import ActionBatch, ActionExecution, ExecutionFact, ExecutionState
from .errors import ActionContractError, ActionInvariantError
from .executor import (
    ActionExecutionCancelled, ActionExecutionContext, ActionExecutionControl,
    ActionExecutor, ExecutorRegistry,
)
from .hooks import ActionExecutionHookPipeline
from .result import (
    ActionFailureDisposition, ActionLocalFailure, ActionResult, ActionResultStatus,
    ActionTraceMode,
)
from .specs import ActionParallelPolicy


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
        self, *, executors: ExecutorRegistry,
        hooks: ActionExecutionHookPipeline | None = None,
        planner: BatchConcurrencyPlanner | None = None,
        max_workers: int = 8,
        cooperative_cancel_grace_seconds: float = 0.05,
        process_cancel_grace_seconds: float = 1.0,
        observations: ObservationEmitter | None = None,
    ) -> None:
        if isinstance(max_workers, bool) or max_workers <= 0:
            raise ActionContractError("Action concurrency must be positive")
        if min(cooperative_cancel_grace_seconds, process_cancel_grace_seconds) < 0:
            raise ActionContractError("Action cancellation grace cannot be negative")
        self._executors = executors
        self._hooks = hooks or ActionExecutionHookPipeline()
        self._planner = planner or BatchConcurrencyPlanner()
        self._max_workers = max_workers
        self._bridge = RuntimeActionBridge()

    def _schedule_group(self, group: tuple[ActionExecution, ...]) -> tuple[ActionExecution, ...]:
        """Attach deterministic deadlines before scheduling a group."""
        return tuple(
            replace(item, framework=replace(
                item.framework,
                deadline=monotonic() + item.framework.timeout_seconds
                if item.framework.timeout_seconds is not None else None,
            )) for item in group
        )

    async def run(
        self, batch: ActionBatch, context: ActionExecutionContext,
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
        self, group: tuple[ActionExecution, ...], context: ActionExecutionContext,
    ) -> tuple[ActionResult, ...]:
        gate = asyncio.Semaphore(self._max_workers)
        contexts = [replace(context, control=ActionExecutionControl(),
                            owner_operations=JoinedOperations()) for _ in group]
        tasks = [asyncio.create_task(self._limited(execution, owned, gate))
                 for execution, owned in zip(group, contexts, strict=True)]
        try:
            pending = set(tasks)
            while pending:
                done, pending = await asyncio.wait(
                    pending, timeout=0.05, return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    task.result()
                if context.cancelled is not None and context.cancelled():
                    raise ActionExecutionCancelled("turn_cancelled")
            return tuple(task.result() for task in tasks)
        finally:
            for task, owned in zip(tasks, contexts, strict=True):
                if not task.done():
                    owned.control.request_cancel("cancelled")
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _limited(
        self, execution: ActionExecution, context: ActionExecutionContext,
        gate: asyncio.Semaphore,
    ) -> ActionResult:
        started = False
        settled = False
        try:
            async with gate:
                if context.cancelled is not None and context.cancelled():
                    raise ActionExecutionCancelled("turn_cancelled")
                timeout = execution.framework.timeout_seconds
                execution = replace(execution, framework=replace(
                    execution.framework,
                    deadline=monotonic() + timeout if timeout is not None else None,
                ))
                context.control.deadline = execution.framework.deadline
                self._record(context, execution, ExecutionState.STARTED)
                started = True
                work = asyncio.create_task(self._run_one(execution, context))
                try:
                    while True:
                        remaining = context.control.remaining_seconds()
                        if remaining is not None and remaining <= 0:
                            context.control.request_cancel("timeout")
                        try:
                            result = await asyncio.wait_for(asyncio.shield(work), timeout=0.05)
                            break
                        except TimeoutError:
                            if context.control.is_cancelled():
                                result = await asyncio.shield(work)
                                break
                            continue
                finally:
                    if not work.done():
                        await asyncio.shield(work)
                self._record(context, execution, ExecutionState.SETTLED, result)
                settled = True
                context.owner_operations.check_cancelled()
                return result
        except (asyncio.CancelledError, ActionExecutionCancelled):
            context.control.request_cancel("cancelled")
            if not settled:
                self._record(context, execution,
                    ExecutionState.CANCELLED if started else ExecutionState.NOT_EXECUTED)
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
        self, execution: ActionExecution, context: ActionExecutionContext,
    ) -> ActionResult:
        hook_result = self._hooks.run(execution, context=context)
        if hook_result is not None:
            return hook_result
        executor = self._executors.get(execution.action.backend.handler)
        try:
            result = await self._execute(executor, execution, context)
        except ActionExecutionCancelled as exc:
            result = self._timeout_result(execution, reason="cancelled")
            if exc.args:
                result = replace(result, frame_data={**result.frame_data, "cancel_reason": str(exc.args[0])})
            return result
        if not isinstance(result, ActionResult):
            raise ActionInvariantError("Action executor returned an invalid result object")
        if self._result_mismatch(execution, result):
            raise ActionInvariantError("Action executor returned another invocation's result")
        if self._trace_projection_mismatch(execution, result):
            raise ActionInvariantError("Action executor violated the result trace policy")
        # Already committed owner results remain true after a late deadline.
        return result

    async def _execute(
        self, executor: ActionExecutor, execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        if context.module_runner is None:
            value = executor.execute(execution, context)
            if inspect.isawaitable(value):
                return await value
            return value

        async def invoke(module_scope: RunScope) -> ActionResult:
            value = executor.execute(replace(execution, framework=replace(
                execution.framework, scope=module_scope,
            )), context)
            if inspect.isawaitable(value):
                return await value
            return value

        return cast(ActionResult, await context.module_runner.run(
            scope=execution.framework.scope, name=execution.framework.invoke_id,
            callback=invoke,
        ))

    @staticmethod
    def _record(
        context: ActionExecutionContext, execution: ActionExecution,
        state: ExecutionState, result: ActionResult | None = None,
    ) -> None:
        if context.record_execution is not None:
            context.record_execution(ExecutionFact(
                call=execution.call, framework=execution.framework, state=state, result=result,
            ))

    @staticmethod
    def _timeout_result(execution: ActionExecution, *, reason: str = "execution_timeout") -> ActionResult:
        return ActionResult.timeout(
            call_id=execution.call.call_id, invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id, action_name=execution.call.action_name,
            sequence=execution.call.sequence, domain=execution.framework.domain,
            failure=ActionLocalFailure(
                reason=reason, scope="action.timeout",
                disposition=ActionFailureDisposition.RETRY_SAME,
                feedback="Action exceeded its execution deadline.",
            ),
            frame_data={"executor_started": True, "cancel_reason": "timeout",
                         "executor_leaked": False, "late_success": False,
                         "cancel_requested": True},
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
    def _trace_projection_mismatch(execution: ActionExecution, result: ActionResult) -> bool:
        if result.status is not ActionResultStatus.SUCCESS:
            return False
        return (execution.action.runtime.result.trace_mode is ActionTraceMode.FOLDABLE) != (
            result.trace_projection is not None
        )
