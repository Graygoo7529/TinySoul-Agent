"""Native Python action executor helpers."""

from __future__ import annotations

from collections.abc import Callable

from tinysoul.infra.json import JsonObject, to_json_object

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
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
        payload = to_json_object(self._function(execution, context))
        return ActionResult.success(
            invoke_id=execution.framework.invoke_id,
            action_name=execution.call.action_name,
            payload=payload,
        )
