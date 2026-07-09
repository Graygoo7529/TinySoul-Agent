"""Native Python action executor helpers."""

from __future__ import annotations

from collections.abc import Callable

from tinysoul.infra.json import JsonObject, to_json_object

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionCancelled, ActionExecutionContext
from tinysoul.action.core.result import ActionResult

NativeActionFunction = Callable[[ActionExecution, ActionExecutionContext], JsonObject]


class NativeFunctionExecutor:
    """Execute a registered Python function as an action."""

    def __init__(self, function: NativeActionFunction) -> None:
        self._function = function

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        try:
            payload = to_json_object(self._function(execution, context))
        except ActionExecutionCancelled as exc:
            return ActionResult.timeout(
                call_id=execution.call.call_id,
                invoke_id=execution.framework.invoke_id,
                batch_id=execution.framework.batch_id,
                action_name=execution.call.action_name,
                sequence=execution.call.sequence,
                domain=execution.framework.domain,
                model_feedback="Action stopped after cancellation was requested.",
                frame_data={
                    "reason": str(exc) or "cancelled",
                    "cancel_requested": True,
                    "executor_started": True,
                    "executor_leaked": False,
                    "late_success": False,
                },
            )
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload=payload,
        )
