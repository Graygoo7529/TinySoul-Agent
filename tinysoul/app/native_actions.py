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
    payload: JsonObject = {"text": text}
    references = execution.call.params.get("references", [])
    if isinstance(references, list):
        cleaned = tuple(item for item in references if isinstance(item, str) and item)
        if cleaned:
            payload["references"] = list(cleaned)
    return payload
