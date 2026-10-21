"""Safe provider-neutral payloads for MODEL observation events."""

from __future__ import annotations

from tinysoul.infra.json import (
    JsonObject,
    JsonTypeError,
    JsonValue,
    to_json_object,
)

from ..protocol.messages import (
    MessageStack,
)
from ..protocol.projection import (
    _tool_call_payload,
    message_projection,
    reasoning_projection,
)
from ..protocol.responses import RawResponse
from ..protocol.tools import ToolScope


def task_request_observation(
    messages: MessageStack,
    tools: ToolScope,
) -> JsonObject:
    return {
        "messages": [message_projection(message) for message in messages.messages],
        "provenance": [origin.to_json() for origin in messages.provenance],
        "resolved_references": messages.resolved_references,
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "kind": tool.kind.value,
                "strict": tool.strict,
            }
            for tool in tools.visible_tools()
        ],
        "tool_selection": {
            "allowed_names": list(tools.selection.allowed_names),
            "forced_name": tools.selection.forced_name,
        },
    }


def task_response_observation(response: RawResponse, tools: ToolScope) -> JsonObject:
    kinds = {tool.name: tool.kind for tool in tools.visible_tools()}
    calls: list[JsonValue] = []
    for call in response.tool_calls:
        projected = _tool_call_payload(call)
        # Providers do not own TinySoul tool categories. Resolve missing kinds
        # from this request's scope; this does not imply protocol acceptance.
        kind = call.kind if call.kind is not None else kinds.get(call.name)
        projected["kind"] = kind.value if kind is not None else None
        calls.append(projected)
    payload: JsonObject = {
        "model_id": response.model_id,
        "provider_id": response.provider_id,
        "stop_reason": response.stop_reason.value,
        "answer_text": response.answer_text,
        "tool_calls": calls,
    }
    payload["usage"] = response.usage.to_json()
    payload["metadata"] = _safe_mapping(response.metadata)
    if response.reasoning is not None:
        payload["reasoning"] = reasoning_projection(response.reasoning)
    return payload


def _safe_mapping(value: dict[str, object]) -> JsonObject:
    try:
        return to_json_object(value)
    except (JsonTypeError, RecursionError):
        return {
            "unavailable": True,
            "value_types": {key: type(item).__name__ for key, item in value.items()},
        }
