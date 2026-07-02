"""Action batch execution runner."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from time import monotonic

from .call import ActionBatch, ActionExecution
from .catalog import ActionCatalog
from .executor import ActionExecutionContext, ExecutorRegistry
from .hooks import ActionHookPipeline
from .result import ActionResult, ActionResultStage
from .specs import ActionParallelPolicy


class BatchConcurrencyPlanner:
    """Split executions into serial groups based on action parallel policy."""

    def plan(
        self,
        batch: ActionBatch,
        *,
        catalog: ActionCatalog,
    ) -> tuple[tuple[ActionExecution, ...], ...]:
        groups: list[tuple[ActionExecution, ...]] = []
        parallel_group: list[ActionExecution] = []
        for execution in batch.executions:
            action = catalog.get_action(execution.call.action_name)
            if action.runtime.parallel_policy is ActionParallelPolicy.ALLOWED:
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
    leaked_timeout_invoke_id: str | None = None


class ActionBatchRunner:
    """Run an action batch and return one result per action execution."""

    def __init__(
        self,
        *,
        catalog: ActionCatalog,
        executors: ExecutorRegistry,
        hooks: ActionHookPipeline | None = None,
        planner: BatchConcurrencyPlanner | None = None,
        max_workers: int = 8,
    ) -> None:
        self._catalog = catalog
        self._executors = executors
        self._hooks = hooks or ActionHookPipeline()
        self._planner = planner or BatchConcurrencyPlanner()
        self._max_workers = max_workers

    def run(
        self,
        batch: ActionBatch,
        context: ActionExecutionContext,
    ) -> tuple[ActionResult, ...]:
        results: list[ActionResult] = []
        groups = self._planner.plan(batch, catalog=self._catalog)
        for index, group in enumerate(groups):
            group_run = self._run_group(group, context)
            results.extend(group_run.results)
            if group_run.leaked_timeout_invoke_id is not None:
                for remaining_group in groups[index + 1 :]:
                    results.extend(
                        self._blocked_by_leaked_timeout(
                            remaining_group,
                            blocked_by=group_run.leaked_timeout_invoke_id,
                        )
                    )
                break
        order = {
            execution.framework.invoke_id: index
            for index, execution in enumerate(batch.executions)
        }
        return tuple(sorted(results, key=lambda result: order[result.invoke_id]))

    def _run_group(
        self,
        group: tuple[ActionExecution, ...],
        context: ActionExecutionContext,
    ) -> _GroupRun:
        workers = min(self._max_workers, len(group))
        results: list[ActionResult] = []
        leaked_timeout_invoke_id: str | None = None
        pool = ThreadPoolExecutor(max_workers=workers)
        wait_for_workers = True
        try:
            futures = {
                pool.submit(self._run_one, execution, context): execution
                for execution in group
            }
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
                        execution = futures[future]
                        future.cancel()
                        executor_leaked = not future.cancelled()
                        results.append(
                            ActionResult.timeout(
                                invoke_id=execution.framework.invoke_id,
                                action_name=execution.call.action_name,
                                model_feedback="Action timed out during execution.",
                                frame_data={
                                    "executor_leaked": executor_leaked,
                                },
                            )
                        )
                        if executor_leaked:
                            leaked_timeout_invoke_id = execution.framework.invoke_id
                            wait_for_workers = False
                    pending -= expired
                    continue
                for future in done:
                    results.append(future.result())
        finally:
            pool.shutdown(wait=wait_for_workers, cancel_futures=True)
        return _GroupRun(
            results=tuple(results),
            leaked_timeout_invoke_id=leaked_timeout_invoke_id,
        )

    def _blocked_by_leaked_timeout(
        self,
        group: tuple[ActionExecution, ...],
        *,
        blocked_by: str,
    ) -> tuple[ActionResult, ...]:
        return tuple(
            ActionResult.failed(
                invoke_id=execution.framework.invoke_id,
                action_name=execution.call.action_name,
                stage=ActionResultStage.EXECUTE,
                model_feedback=(
                    "Action was not started because a previous action timed out "
                    "and may still be running."
                ),
                frame_data={
                    "blocked_by_invoke_id": blocked_by,
                    "reason": "previous_action_timeout_leak",
                },
            )
            for execution in group
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
            return ActionResult.timeout(
                invoke_id=execution.framework.invoke_id,
                action_name=execution.call.action_name,
                model_feedback="Action timed out before execution started.",
            )
        hook_result = self._hooks.run(
            execution,
            catalog=self._catalog,
            context=context,
        )
        if hook_result is not None:
            return hook_result
        if execution.framework.is_expired():
            return ActionResult.timeout(
                invoke_id=execution.framework.invoke_id,
                action_name=execution.call.action_name,
                model_feedback="Action timed out after hook checks.",
            )
        try:
            action = self._catalog.get_action(execution.call.action_name)
            executor = self._executors.get(action.backend.handler)
            result = executor.execute(execution, context)
        except Exception as exc:
            return ActionResult.failed(
                invoke_id=execution.framework.invoke_id,
                action_name=execution.call.action_name,
                stage=ActionResultStage.EXECUTE,
                model_feedback=f"Action execution failed: {exc}",
                frame_data={"error_type": type(exc).__name__},
            )
        if execution.framework.is_expired() and result.status.value == "success":
            return ActionResult.timeout(
                invoke_id=execution.framework.invoke_id,
                action_name=execution.call.action_name,
                model_feedback="Action timed out before result collection.",
            )
        return result
