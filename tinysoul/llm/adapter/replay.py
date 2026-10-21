"""Bind opaque output to the assistant content and ordered tool calls it describes."""

from hashlib import sha256

from tinysoul.infra.json import JsonObject, dumps_json
from tinysoul.llm.protocol.messages import AssistantMessage, TextPart
from tinysoul.llm.protocol.reasoning import NativeReplay, NativeReplayMode
from tinysoul.llm.protocol.tools import ToolCallRecord

from .base import ProviderRequest
from .catalog import adapter_spec


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


def capture_replay(
    request: ProviderRequest,
    mode: NativeReplayMode,
    items: tuple[JsonObject, ...],
    text: str,
    calls: tuple[ToolCallRecord, ...],
) -> NativeReplay:
    return NativeReplay(
        mode=mode,
        api_mode=adapter_spec(request.model.adapter).api_mode,
        adapter=request.model.adapter,
        provider_id=request.binding.provider_id,
        provider_model=request.binding.provider_model,
        variant=request.model.adapter_options.variant,
        ordered_items=items,
        message_fingerprint=response_fingerprint(text, calls),
    )


def matching_replay(
    message: AssistantMessage,
    request: ProviderRequest,
    *,
    mode: NativeReplayMode | None = None,
) -> tuple[JsonObject, ...]:
    replay = message.reasoning.native_replay if message.reasoning else None
    if (
        replay is not None
        and (mode is None or replay.mode is mode)
        and (
            replay.api_mode,
            replay.adapter,
            replay.provider_id,
            replay.provider_model,
            replay.variant,
            replay.message_fingerprint,
        )
        == (
            adapter_spec(request.model.adapter).api_mode,
            request.model.adapter,
            request.binding.provider_id,
            request.binding.provider_model,
            request.model.adapter_options.variant,
            message_fingerprint(message),
        )
    ):
        return replay.ordered_items
    return ()
