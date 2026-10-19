"""Bind opaque output to the assistant content and ordered tool calls it describes."""

from hashlib import sha256

from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.llm.protocol.messages import AssistantMessage, TextPart
from tinysoul.llm.protocol.tools import ToolCallRecord


def response_fingerprint(text: str, calls: tuple[ToolCallRecord, ...]) -> str:
    payload: JsonObject = {
        "text": text,
        "calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in calls
        ],
    }
    return sha256(dumps_json(payload).encode("utf-8")).hexdigest()


def message_fingerprint(message: AssistantMessage) -> str | None:
    if not all(isinstance(part, TextPart) for part in message.parts):
        return None
    return response_fingerprint(
        "".join(part.text for part in message.parts if isinstance(part, TextPart)),
        message.tool_calls,
    )
