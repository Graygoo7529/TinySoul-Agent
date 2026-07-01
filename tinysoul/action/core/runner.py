"""Action batch execution runner."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

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
        for group in self._planner.plan(batch, catalog=self._catalog):
            results.extend(self._run_group(group, context))
        order = {
            execution.framework.invoke_id: index
            for index, execution in enumerate(batch.executions)
        }
        return tuple(sorted(results, key=lambda result: order[result.invoke_id]))

    def _run_group(
        self,
        group: tuple[ActionExecution, ...],
        context: ActionExecutionContext,
    ) -> tuple[ActionResult, ...]:
        if len(group) == 1:
            return (self._run_one(group[0], context),)
        workers = min(self._max_workers, len(group))
        results: list[ActionResult] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._run_one, execution, context): execution
                for execution in group
            }
            for future in as_completed(futures):
                results.append(future.result())
        return tuple(results)

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
