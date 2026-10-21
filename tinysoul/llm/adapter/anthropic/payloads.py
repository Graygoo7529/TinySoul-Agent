"""Map TinySoul messages to ordered Anthropic blocks."""

from base64 import b64encode

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.execution.message_rendering import (
    MessageContentRenderer,
    RenderedImage,
    RenderedImageUrl,
    RenderedText,
)
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    MessagePart,
    SystemMessage,
    ToolResultMessage,
)
from tinysoul.llm.protocol.reasoning import NativeReplayMode
from tinysoul.llm.protocol.tools import ToolResultStatus, ToolUse

from ..base import ProviderError, ProviderErrorKind, ProviderRequest
from ..common import cache_boundary
from ..history import (
    assistant_context_parts,
    tool_replay_plan,
    tool_result_content,
    tool_result_text,
)
from ..replay import matching_replay
from ..tool_names import ProviderToolNameMap


def content_blocks(parts: tuple[MessagePart, ...]) -> list[JsonObject]:
    rendered = MessageContentRenderer().render(parts)
    if isinstance(rendered, str):
        return [{"type": "text", "text": rendered}] if rendered else []
    result: list[JsonObject] = []
    for part in rendered:
        if isinstance(part, RenderedText):
            result.append({"type": "text", "text": part.text})
        elif isinstance(part, RenderedImage):
            result.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part.mime_type,
                        "data": b64encode(part.data).decode("ascii"),
                    },
                }
            )
        elif isinstance(part, RenderedImageUrl):
            result.append({"type": "image", "source": {"type": "url", "url": part.url}})
    return result


def message_payload(
    request: ProviderRequest, names: ProviderToolNameMap
) -> tuple[list[JsonObject], list[JsonObject]]:
    system: list[JsonObject] = []
    messages: list[JsonObject] = []
    plan = tool_replay_plan(request.messages.messages)
    renderer = MessageContentRenderer()
    options = request.model.adapter_options.values
    boundary = (
        cache_boundary(request)
        if options.get("prompt_cache_mode") == "explicit"
        else None
    )
    native_tool_call_ids: set[str] = set()
    for index, message in enumerate(request.messages.messages):
        if not isinstance(message, ToolResultMessage):
            native_tool_call_ids.clear()
        role = "user"
        blocks: list[JsonObject]
        if isinstance(message, SystemMessage):
            blocks = content_blocks(message.parts)
            if any(block["type"] != "text" for block in blocks):
                raise ProviderError(
                    "Anthropic system instructions must be text",
                    kind=ProviderErrorKind.CAPABILITY,
                )
            system.extend(blocks)
        else:
            if isinstance(message, AssistantMessage):
                role = "assistant"
                native = (
                    request.tool_use is not ToolUse.DISABLED
                    and index in plan.assistant_indices
                )
                replay = (
                    matching_replay(message, request, mode=NativeReplayMode.SIGNED)
                    if request.model.adapter_options.native_replay_mode()
                    is NativeReplayMode.SIGNED
                    else ()
                )
                expected_calls = [
                    (call.id, names.to_provider_name(call.name))
                    for call in message.tool_calls
                ]
                native_calls = [
                    (item.get("id"), item.get("name"))
                    for item in replay
                    if item.get("type") == "tool_use"
                ]
                blocks = (
                    [to_json_object(item) for item in replay]
                    if replay
                    and native_calls == expected_calls
                    and (not message.tool_calls or native)
                    else []
                )
                if blocks and native:
                    native_tool_call_ids.update(call.id for call in message.tool_calls)
                if not blocks:
                    blocks = content_blocks(
                        assistant_context_parts(message, native_calls=False)
                    )
            elif isinstance(message, ToolResultMessage):
                if message.call_id in native_tool_call_ids:
                    blocks = [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.call_id,
                            "content": tool_result_content(message, renderer=renderer),
                            "is_error": message.status is not ToolResultStatus.OK,
                        }
                    ]
                else:
                    blocks = [
                        {
                            "type": "text",
                            "text": tool_result_text(message, renderer=renderer),
                        }
                    ]
            else:
                blocks = content_blocks(message.parts)
            if blocks:
                if messages and messages[-1]["role"] == role:
                    previous = messages[-1]["content"]
                    assert isinstance(previous, list)
                    previous.extend(blocks)
                else:
                    messages.append({"role": role, "content": list(blocks)})
        if index == boundary:
            if not blocks or blocks[-1].get("type") in {
                "thinking",
                "redacted_thinking",
            }:
                raise ProviderError(
                    "Cache boundary requires a cacheable content block",
                    kind=ProviderErrorKind.CONFIG,
                )
            blocks[-1]["cache_control"] = {
                "type": "ephemeral",
                "ttl": str(options.get("prompt_cache_ttl", "5m")),
            }
    return system, messages
