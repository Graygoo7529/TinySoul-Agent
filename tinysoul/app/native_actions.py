"""Native actions registered by the app assembly layer."""

from __future__ import annotations

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.infra.json import JsonObject


def core_answer(
    execution: ActionExecution,
    context: ActionExecutionContext,
) -> JsonObject:
    """Return the final answer payload for the current user turn."""

    text = execution.call.params.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    return {"text": text}
