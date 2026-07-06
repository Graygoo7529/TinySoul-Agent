"""Action batch execution runner."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from time import monotonic

from tinysoul.infra.json import JsonObject

from .call import ActionBatch, ActionExecution
from .errors import ActionContractError
from .executor import ActionExecutionContext, ActionExecutionControl, ExecutorRegistry
from .hooks import ActionExecutionHookPipeline
from .result import ActionResult, ActionResultStage, ActionResultStatus
from .specs import ActionBackendKind, ActionParallelPolicy


class BatchConcurrencyPlanner:
    """Split executions into serial groups based on action parallel policy."""

    def plan(
        self,
        batch: ActionBatch,
    ) -> tuple[tuple[ActionExecution, ...], ...]:
        groups: list[tuple[ActionExecution, ...]] = []
        parallel_group: list[ActionExecution] = []
        for execution in batch.executions:
            if execution.action.runtime.parallel_policy is ActionParallelPolicy.ALLOWED:
                parallel_group.append(execution)
                continue
            if parallel_group:
                groups.append(tuple(parallel_group))
                parallel_group = []
            groups.append((execution,))
        if parallel_group:
            groups.append(tuple(parallel_group))
        return tuple(groups)


@dataclass(frozen=True)
class _GroupRun:
    results: tuple[ActionResult, ...]
    leaked_timeout_invoke_ids: tuple[str, ...] = ()


class ActionBatchRunner:
    """Run an action batch and return one result per action execution."""

    def __init__(
        self,
        *,
        executors: ExecutorRegistry,
        hooks: ActionExecutionHookPipeline | None = None,
        planner: BatchConcurrencyPlanner | None = None,
        max_workers: int = 8,
        cooperative_cancel_grace_seconds: float = 0.05,
        process_cancel_grace_seconds: float = 1.0,
    ) -> None:
        if max_workers <= 0:
            raise ActionContractError("ActionBatchRunner.max_workers must be positive")
        if cooperative_cancel_grace_seconds < 0:
            raise ActionContractError(
                "ActionBatchRunner.cooperative_cancel_grace_seconds cannot be negative"
            )
        if process_cancel_grace_seconds < 0:
            raise ActionContractError(
                "ActionBatchRunner.process_cancel_grace_seconds cannot be negative"
            )
        self._executors = executors
        self._hooks = hooks or ActionExecutionHookPipeline()
        self._planner = planner or BatchConcurrencyPlanner()
        self._max_workers = max_workers
        self._cooperative_cancel_grace_seconds = cooperative_cancel_grace_seconds
        self._process_cancel_grace_seconds = process_cancel_grace_seconds

    def run(
        self,
        batch: ActionBatch,
        context: ActionExecutionContext,
    ) -> tuple[ActionResult, ...]:
        results: list[ActionResult] = []
        groups = self._planner.plan(batch)
        for index, group in enumerate(groups):
            group_run = self._run_group(self._schedule_group(group), context)
            results.extend(group_run.results)
            if group_run.leaked_timeout_invoke_ids:
                for remaining_group in groups[index + 1 :]:
                    results.extend(
                        self._blocked_by_leaked_timeout(
                            remaining_group,
                            blocked_by=group_run.leaked_timeout_invoke_ids,
                        )
                    )
                break
        return tuple(sorted(results, key=lambda result: result.sequence))

    def _run_group(
        self,
        group: tuple[ActionExecution, ...],
        context: ActionExecutionContext,
        ) -> _GroupRun:
        workers = min(self._max_workers, len(group))
        results: list[ActionResult] = []
        leaked_timeout_invoke_ids: list[str] = []
        pool = ThreadPoolExecutor(max_workers=workers)
        wait_for_workers = True
        try:
            futures: dict[Future[ActionResult], ActionExecution] = {}
            contexts: dict[Future[ActionResult], ActionExecutionContext] = {}
            for execution in group:
                execution_context = self._context_for_execution(execution, context)
                future = pool.submit(self._run_one, execution, execution_context)
                futures[future] = execution
                contexts[future] = execution_context
            pending: set[Future[ActionResult]] = set(futures)
            while pending:
                timeout = self._remaining_timeout(futures[future] for future in pending)
                done, pending = wait(pending, timeout=timeout)
                if not done and pending:
                    expired = {
                        future
                        for future in pending
                        if futures[future].framework.is_expired()
                    }
                    if not expired:
                        continue
                    for future in expired:
                        contexts[future].control.request_cancel("timeout")
                    cancelled_done, still_expired = wait(
                        expired,
                        timeout=self._cancel_grace_seconds(
                            futures[future] for future in expired
                        ),
                    )
                    for future in cancelled_done:
                        execution = futures[future]
                        results.append(self._future_result(future, execution))
                    for future in expired:
                        if future in cancelled_done:
                            continue
                        execution = futures[future]
                        future.cancel()
                        executor_leaked = not future.cancelled()
                        results.append(
                            self._timeout_result(
                                execution,
                                model_feedback="Action timed out during execution.",
                                frame_data={
                                    "cancel_requested": True,
                                    "executor_leaked": executor_leaked,
                                },
                            )
                        )
                        if executor_leaked:
                            leaked_timeout_invoke_ids.append(execution.framework.invoke_id)
                            wait_for_workers = False
                    pending -= still_expired
                    pending -= expired
                    continue
                for future in done:
                    execution = futures[future]
                    results.append(self._future_result(future, execution))
        finally:
            pool.shutdown(wait=wait_for_workers, cancel_futures=True)
        return _GroupRun(
            results=tuple(results),
            leaked_timeout_invoke_ids=tuple(leaked_timeout_invoke_ids),
        )

    def _blocked_by_leaked_timeout(
        self,
        group: tuple[ActionExecution, ...],
        *,
        blocked_by: tuple[str, ...],
    ) -> tuple[ActionResult, ...]:
        return tuple(
            ActionResult.failed(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                stage=ActionResultStage.SCHEDULE,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                model_feedback=(
                    "Action was not started because a previous action timed out "
                    "and may still be running."
                ),
                frame_data={
                    "blocked_by_invoke_ids": list(blocked_by),
                    "reason": "previous_action_timeout_leak",
                },
            )
            for execution in group
        )

    def _context_for_execution(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionExecutionContext:
        return replace(
            context,
            control=ActionExecutionControl(deadline=execution.framework.deadline),
        )

    def _cancel_grace_seconds(self, executions: Iterable[ActionExecution]) -> float:
        for execution in executions:
            if execution.action.backend.kind in {
                ActionBackendKind.SUBPROCESS,
                ActionBackendKind.SCRIPT,
            }:
                return max(
                    self._cooperative_cancel_grace_seconds,
                    self._process_cancel_grace_seconds,
                )
        return self._cooperative_cancel_grace_seconds

    def _schedule_group(
        self,
        group: tuple[ActionExecution, ...],
    ) -> tuple[ActionExecution, ...]:
        return tuple(self._schedule_execution(execution) for execution in group)

    def _schedule_execution(self, execution: ActionExecution) -> ActionExecution:
        timeout = execution.framework.timeout_seconds
        deadline = monotonic() + timeout if timeout is not None else None
        return replace(
            execution,
            framework=replace(execution.framework, deadline=deadline),
        )

    def _remaining_timeout(self, executions: Iterable[ActionExecution]) -> float | None:
        deadlines = [
            execution.framework.deadline
            for execution in executions
            if execution.framework.deadline is not None
        ]
        if not deadlines:
            return None
        return max(0.0, min(deadlines) - monotonic())

    def _run_one(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        if execution.framework.is_expired():
            return self._timeout_result(
                execution,
                model_feedback="Action timed out before execution started.",
            )
        hook_result = self._hooks.run(
            execution,
            context=context,
        )
        if hook_result is not None:
            return hook_result
        if execution.framework.is_expired():
            return self._timeout_result(
                execution,
                model_feedback="Action timed out after hook checks.",
            )
        try:
            executor = self._executors.get(execution.action.backend.handler)
            result = executor.execute(execution, context)
        except Exception as exc:
            return ActionResult.failed(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                stage=ActionResultStage.EXECUTE,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                model_feedback=f"Action execution failed: {exc}",
                frame_data={"error_type": type(exc).__name__},
            )
        if not isinstance(result, ActionResult):
            return ActionResult.failed(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                stage=ActionResultStage.EXECUTE,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                model_feedback="Action executor returned an invalid result object.",
                frame_data={
                    "reason": "invalid_executor_result",
                    "result_type": type(result).__name__,
                },
            )
        result_mismatch = self._result_mismatch(execution, result)
        if result_mismatch:
            return ActionResult.failed(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                stage=ActionResultStage.EXECUTE,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                model_feedback="Action executor returned a result for a different invocation.",
                frame_data={
                    "reason": "executor_result_mismatch",
                    "mismatch": result_mismatch,
                },
            )
        if execution.framework.is_expired() and result.status is ActionResultStatus.SUCCESS:
            return self._timeout_result(
                execution,
                model_feedback="Action timed out before result collection.",
                frame_data={"late_success": True},
            )
        return result

    def _future_result(
        self,
        future: Future[ActionResult],
        execution: ActionExecution,
    ) -> ActionResult:
        try:
            return future.result()
        except Exception as exc:
            return self._internal_failure(
                execution,
                model_feedback=f"Action runner failed: {exc}",
                frame_data={"error_type": type(exc).__name__},
            )

    def _timeout_result(
        self,
        execution: ActionExecution,
        *,
        model_feedback: str,
        frame_data: JsonObject | None = None,
    ) -> ActionResult:
        return ActionResult.timeout(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            model_feedback=model_feedback,
            frame_data=frame_data,
        )

    def _internal_failure(
        self,
        execution: ActionExecution,
        *,
        model_feedback: str,
        frame_data: JsonObject,
    ) -> ActionResult:
        return ActionResult.failed(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            stage=ActionResultStage.EXECUTE,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            model_feedback=model_feedback,
            frame_data=frame_data,
        )

    def _result_mismatch(
        self,
        execution: ActionExecution,
        result: ActionResult,
    ) -> JsonObject:
        expected: JsonObject = {
            "call_id": execution.call.call_id,
            "invoke_id": execution.framework.invoke_id,
            "batch_id": execution.framework.batch_id,
            "action_name": execution.call.action_name,
            "sequence": execution.call.sequence,
            "domain": execution.framework.domain,
        }
        actual: JsonObject = {
            "call_id": result.call_id,
            "invoke_id": result.invoke_id,
            "batch_id": result.batch_id,
            "action_name": result.action_name,
            "sequence": result.sequence,
            "domain": result.domain,
        }
        mismatch: JsonObject = {}
        for name, expected_value in expected.items():
            if actual[name] != expected_value:
                mismatch[name] = {
                    "expected": expected_value,
                    "actual": actual[name],
                }
        return mismatch
