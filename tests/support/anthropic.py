"""Anthropic SSE fixtures consumed through the real SDK HTTP transport."""

import json

import httpx2
from anthropic.types import Message


def anthropic_sse_response(payload: dict[str, object]) -> httpx2.Response:
    message = Message.model_validate(payload)
    start = message.model_dump(mode="json", exclude_none=True)
    start.update(content=[], stop_reason=None, stop_sequence=None)
    start["usage"] = {
        "input_tokens": message.usage.input_tokens,
        "output_tokens": 0,
    }
    events: list[dict[str, object]] = [{"type": "message_start", "message": start}]
    for index, block in enumerate(message.content):
        initial = block.model_dump(mode="json", exclude_none=True)
        deltas: list[dict[str, object]] = []
        if block.type == "text":
            initial["text"] = ""
            deltas = [
                {"type": "text_delta", "text": part} for part in _parts(block.text)
            ]
        elif block.type == "thinking":
            initial.update(thinking="", signature="")
            deltas = [
                {"type": "thinking_delta", "thinking": part}
                for part in _parts(block.thinking)
            ]
            deltas.append({"type": "signature_delta", "signature": block.signature})
        elif block.type == "tool_use":
            initial["input"] = {}
            deltas = [
                {"type": "input_json_delta", "partial_json": part}
                for part in _parts(json.dumps(block.input))
            ]
        events.append(
            {
                "type": "content_block_start",
                "index": index,
                "content_block": initial,
            }
        )
        events.extend(
            {"type": "content_block_delta", "index": index, "delta": delta}
            for delta in deltas
        )
        events.append({"type": "content_block_stop", "index": index})
    events.extend(
        [
            {
                "type": "message_delta",
                "delta": {
                    "stop_reason": message.stop_reason,
                    "stop_sequence": message.stop_sequence,
                },
                "usage": message.usage.model_dump(mode="json", exclude_none=True),
            },
            {"type": "message_stop"},
        ]
    )
    body = "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    )
    return httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, content=body
    )


def _parts(value: str) -> tuple[str, str]:
    midpoint = len(value) // 2
    return value[:midpoint], value[midpoint:]
