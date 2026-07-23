"""Action batch execution runner."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from time import monotonic

from tinysoul.infra.json import JsonObject
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RuntimeException,
    RuntimeTransferInterrupt,
    RunScope,
    emit_observation,
    observation_enabled,
)

from .call import ActionBatch, ActionExecution
from .errors import ActionContractError
from .executor import (
    ActionExecutionContext,
    ActionExecutionControl,
    ActionExecutor,
    ExecutorRegistry,
)
from .hooks import ActionExecutionHookPipeline
from .result import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
    ActionResultStatus,
    ActionTraceMode,
)
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
        observations: ObservationEmitter | None = None,
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
        self._observations = observations or NullObservationEmitter()

    def run(
        self,
        batch: ActionBatch,
        context: ActionExecutionContext,
    ) -> tuple[ActionResult, ...]:
        if batch.executions:
            self._emit(
                batch.executions[0].framework.scope,
                "action.batch.started",
                "Starting action batch.",
                {
                    "batch_id": batch.executions[0].framework.batch_id,
                    "action_count": len(batch.executions),
                },
            )
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
        ordered = tuple(sorted(results, key=lambda result: result.sequence))
        if batch.executions:
            self._emit(
                batch.executions[0].framework.scope,
                "action.batch.completed",
                "Action batch completed.",
                {
                    "batch_id": batch.executions[0].framework.batch_id,
                    "results": [
                        {
                            "action": result.action_name,
                            "call_id": result.call_id,
                            "status": result.status.value,
                            "stage": result.stage.value,
                        }
                        for result in ordered
                    ],
                },
            )
        return ordered

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
                done, pending = wait(
                    pending,
                    timeout=timeout,
                    return_when=FIRST_COMPLETED,
                )
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
                    cancelled_done, _ = wait(
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
                                reason="execution_timeout",
                                frame_data={
                                    "cancel_requested": True,
                                    "executor_started": True,
                                    "executor_leaked": executor_leaked,
                                },
                            )
                        )
                        if executor_leaked:
                            leaked_timeout_invoke_ids.append(execution.framework.invoke_id)
                            wait_for_workers = False
                    pending -= expired
                    continue
                for future in done:
                    execution = futures[future]
                    results.append(self._future_result(future, execution))
        except (RuntimeException, RuntimeTransferInterrupt):
            scope = group[0].framework.scope if group else RunScope()
            self._emit(
                scope,
                "action.batch.transfer",
                "Action batch propagated a runtime transfer.",
                {"unfinished_action_count": sum(not future.done() for future in futures)},
            )
            unfinished = {future for future in futures if not future.done()}
            transfer_workers_finished = self._cancel_for_runtime_transfer(
                unfinished,
                futures=futures,
                contexts=contexts,
            )
            wait_for_workers = wait_for_workers and transfer_workers_finished
            raise
        finally:
            pool.shutdown(wait=wait_for_workers, cancel_futures=True)
        return _GroupRun(
            results=tuple(results),
            leaked_timeout_invoke_ids=tuple(leaked_timeout_invoke_ids),
        )

    def _emit(
        self,
        scope: RunScope,
        name: str,
        message: str,
        payload: JsonObject,
    ) -> None:
        if not observation_enabled(
            self._observations,
            ObservationLevel.VERBOSE,
        ):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name=name,
                level=ObservationLevel.VERBOSE,
                source="action.runner",
                scope=scope,
                message=message,
                payload=payload,
            ),
        )

    def _cancel_for_runtime_transfer(
        self,
        pending: set[Future[ActionResult]],
        *,
        futures: dict[Future[ActionResult], ActionExecution],
        contexts: dict[Future[ActionResult], ActionExecutionContext],
    ) -> bool:
        """Cancel sibling actions and return whether shutdown may wait for them."""

        for future in pending:
            contexts[future].control.request_cancel("runtime_transfer")
            future.cancel()
        running = {future for future in pending if not future.done()}
        if not running:
            return True
        _, leaked = wait(
            running,
            timeout=self._cancel_grace_seconds(
                futures[future] for future in running
            ),
        )
        for future in leaked:
            future.cancel()
        return not leaked

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
                failure=ActionLocalFailure(
                    reason="previous_action_timeout_leak",
                    scope="action.schedule",
                    disposition=ActionFailureDisposition.STOP,
                    feedback=(
                        "Action was not started because a previous action timed out "
                        "and may still be running."
                    ),
                ),
                frame_data={
                    "blocked_by_invoke_ids": list(blocked_by),
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
                ActionBackendKind.SUPERVISED_PROCESS,
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
                reason="deadline_before_start",
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
                reason="deadline_after_hooks",
            )
        try:
            executor = self._executors.get(execution.action.backend.handler)
            result = self._execute(executor, execution, context)
        except (RuntimeException, RuntimeTransferInterrupt):
            raise
        except Exception as exc:
            return ActionResult.failed(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                stage=ActionResultStage.EXECUTE,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                failure=ActionLocalFailure(
                    reason="executor_raised",
                    scope="action.execute",
                    disposition=ActionFailureDisposition.STOP,
                    feedback=f"Action execution failed: {exc}",
                ),
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
                failure=ActionLocalFailure(
                    reason="invalid_executor_result",
                    scope="action.execute",
                    disposition=ActionFailureDisposition.STOP,
                    feedback="Action executor returned an invalid result object.",
                ),
                frame_data={
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
                failure=ActionLocalFailure(
                    reason="executor_result_mismatch",
                    scope="action.execute",
                    disposition=ActionFailureDisposition.STOP,
                    feedback=(
                        "Action executor returned a result for a different invocation."
                    ),
                ),
                frame_data={
                    "mismatch": result_mismatch,
                },
            )
        if execution.framework.is_expired() and result.status is ActionResultStatus.SUCCESS:
            return self._timeout_result(
                execution,
                model_feedback="Action timed out before result collection.",
                reason="late_success_timeout",
                frame_data={
                    "executor_started": True,
                    "late_success": True,
                },
            )
        projection_mismatch = self._trace_projection_mismatch(execution, result)
        if projection_mismatch:
            return ActionResult.failed(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                stage=ActionResultStage.EXECUTE,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                failure=ActionLocalFailure(
                    reason="result_trace_policy_mismatch",
                    scope="action.trace_policy",
                    disposition=ActionFailureDisposition.STOP,
                    feedback=(
                        "Action executor result did not satisfy its configured trace policy."
                    ),
                ),
                frame_data=projection_mismatch,
            )
        return result

    def _execute(
        self,
        executor: ActionExecutor,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        module_runner = context.module_runner
        if module_runner is None:
            return executor.execute(execution, context)

        def invoke(module_scope: RunScope) -> ActionResult:
            module_execution = replace(
                execution,
                framework=replace(execution.framework, scope=module_scope),
            )
            return executor.execute(module_execution, context)

        return module_runner.run(
            scope=execution.framework.scope,
            name=execution.framework.invoke_id,
            callback=invoke,
        )

    def _future_result(
        self,
        future: Future[ActionResult],
        execution: ActionExecution,
    ) -> ActionResult:
        try:
            return future.result()
        except (RuntimeException, RuntimeTransferInterrupt):
            raise
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
        reason: str,
        frame_data: JsonObject | None = None,
    ) -> ActionResult:
        stable_frame: JsonObject = {
            "cancel_requested": False,
            "executor_started": False,
            "executor_leaked": False,
            "late_success": False,
        }
        if frame_data is not None:
            stable_frame.update(frame_data)
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
                feedback=model_feedback,
            ),
            frame_data=stable_frame,
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
            failure=ActionLocalFailure(
                reason="runner_internal_failure",
                scope="action.runner",
                disposition=ActionFailureDisposition.STOP,
                feedback=model_feedback,
            ),
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

    def _trace_projection_mismatch(
        self,
        execution: ActionExecution,
        result: ActionResult,
    ) -> JsonObject:
        if result.status is not ActionResultStatus.SUCCESS:
            return {}
        mode = execution.action.runtime.result.trace_mode
        has_projection = result.trace_projection is not None
        if mode is ActionTraceMode.FOLDABLE and not has_projection:
            return {
                "configured_trace_mode": mode.value,
                "projection_present": False,
            }
        if mode is ActionTraceMode.STANDARD and has_projection:
            return {
                "configured_trace_mode": mode.value,
                "projection_present": True,
            }
        return {}
