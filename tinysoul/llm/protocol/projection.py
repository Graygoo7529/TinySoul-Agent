"""Provider-neutral readable message values shared by observation and Context views."""

from __future__ import annotations

from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit

from tinysoul.infra.json import JsonObject

from .messages import (
    AssistantMessage,
    ImagePart,
    ImageUrlPart,
    JsonPart,
    Message,
    SystemMessage,
    TextPart,
    ToolResultMessage,
)
from .reasoning import Reasoning
from .tools import ToolCallRecord


def message_projection(message: Message) -> JsonObject:
    role = "user"
    if isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, AssistantMessage):
        role = "assistant"
    elif isinstance(message, ToolResultMessage):
        role = "tool_result"
    payload: JsonObject = {
        "role": role,
        "label": message.label,
        "parts": [_part_payload(part) for part in message.parts],
    }
    if isinstance(message, AssistantMessage):
        payload["tool_calls"] = [
            _tool_call_payload(call) for call in message.tool_calls
        ]
        if message.reasoning is not None:
            payload["reasoning"] = reasoning_projection(message.reasoning)
    if isinstance(message, ToolResultMessage):
        payload["call_id"] = message.call_id
        payload["tool_name"] = message.tool_name
        payload["status"] = message.status.value
    return payload


def _part_payload(part: TextPart | JsonPart | ImagePart | ImageUrlPart) -> JsonObject:
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text}
    if isinstance(part, JsonPart):
        return {"type": "json", "value": part.value}
    if isinstance(part, ImagePart):
        return {
            "type": "image",
            "mime_type": part.mime_type,
            "size": len(part.data),
            "digest": sha256(part.data).hexdigest(),
        }
    return {"type": "image_url", "url": _safe_image_url(part.url)}


def _tool_call_payload(call: ToolCallRecord) -> JsonObject:
    return {
        "id": call.id,
        "name": call.name,
        "arguments": call.arguments,
        "kind": call.kind.value if call.kind is not None else None,
    }


def _safe_image_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return "<invalid-url>"
    if parsed.scheme == "data":
        return "data:<redacted>"
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def reasoning_projection(reasoning: Reasoning) -> JsonObject:
    replay = reasoning.native_replay
    return {
        "summary": reasoning.summary,
        "native_replay": None if replay is None else {
            "mode": replay.mode.value,
            "api_mode": replay.api_mode.value,
            "adapter": replay.adapter.value,
            "provider_id": replay.provider_id,
            "provider_model": replay.provider_model,
        },
    }
