"""Map TinySoul messages to ordered Anthropic blocks."""

from base64 import b64encode
from hashlib import sha256

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
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
from tinysoul.llm.protocol.models import ModelCapability
from tinysoul.llm.protocol.reasoning import NativeReplayMode
from tinysoul.llm.protocol.tools import ToolResultStatus, ToolUse

from ..base import ProviderError, ProviderErrorKind, ProviderRequest
from ..common import cache_boundaries, cache_ttl
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
    boundaries = {point.message_index: point for point in cache_boundaries(request)}
    native_tool_call_ids: set[str] = set()
    last_cacheable: JsonObject | None = None
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
                current_prefix = prefix_fingerprint(system, messages, request, names)
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
                saved = message.reasoning.native_replay if message.reasoning else None
                if (
                    replay
                    and options.get("replay_prefix_binding") is True
                    and (saved is None or saved.prefix_fingerprint != current_prefix)
                ):
                    replay = ()
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
                if not blocks:
                    blocks = content_blocks(
                        assistant_context_parts(message, native_calls=native)
                    )
                    if native:
                        blocks.extend(
                            {
                                "type": "tool_use",
                                "id": call.id,
                                "name": names.to_provider_name(call.name),
                                "input": call.arguments,
                            }
                            for call in message.tool_calls
                        )
                if native:
                    native_tool_call_ids.update(call.id for call in message.tool_calls)
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
        last_cacheable = next(
            (
                block
                for block in reversed(blocks)
                if block.get("type") not in {"thinking", "redacted_thinking"}
            ),
            last_cacheable,
        )
        if index in boundaries and last_cacheable is not None:
            last_cacheable["cache_control"] = {
                "type": "ephemeral",
                "ttl": cache_ttl(request, boundaries[index], "5m"),
            }
    return system, messages


def automatic_cache_control(
    request: ProviderRequest, system: list[JsonObject], messages: list[JsonObject]
) -> JsonObject | None:
    """Validate the actual block order and merge a coincident automatic boundary."""
    blocks = list(system)
    for message in messages:
        content = message["content"]
        assert isinstance(content, list)
        blocks.extend(block for block in content if isinstance(block, dict))
    cacheable = [
        block
        for block in blocks
        if block.get("type") not in {"thinking", "redacted_thinking"}
    ]
    markers = [
        block["cache_control"] for block in cacheable if "cache_control" in block
    ]
    options = request.model.adapter_options.values
    automatic: JsonObject | None = None
    if (
        request.model.supports(ModelCapability.PROMPT_CACHE)
        and options.get("prompt_cache_mode") == "automatic"
        and cacheable
        and "cache_control" not in cacheable[-1]
    ):
        automatic = {
            "type": "ephemeral",
            "ttl": str(options.get("prompt_cache_ttl", "5m")),
        }
        markers.append(automatic)
    if len(markers) > 4:
        raise ProviderError(
            "Anthropic supports at most four cache boundaries",
            kind=ProviderErrorKind.CONFIG,
        )
    short_seen = False
    for marker in markers:
        assert isinstance(marker, dict)
        if marker.get("ttl") == "1h" and short_seen:
            raise ProviderError(
                "Anthropic longer cache TTL must precede shorter TTL",
                kind=ProviderErrorKind.CONFIG,
            )
        short_seen = short_seen or marker.get("ttl", "5m") == "5m"
    return automatic


def tools_payload(
    request: ProviderRequest, names: ProviderToolNameMap
) -> list[JsonObject]:
    if request.tool_use is ToolUse.DISABLED:
        return []
    return [
        {
            "name": names.to_provider_name(tool.name),
            "description": tool.description,
            "input_schema": tool.parameters,
            **({"strict": True} if tool.strict else {}),
        }
        for tool in request.tool_scope.visible_tools()
    ]


def prefix_fingerprint(
    system: list[JsonObject],
    messages: list[JsonObject],
    request: ProviderRequest,
    names: ProviderToolNameMap,
) -> str:
    """Bind preserved thinking to the actual input prefix, excluding cache metadata."""

    def without_cache(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: without_cache(item)
                for key, item in value.items()
                if key != "cache_control"
            }
        if isinstance(value, list):
            return [without_cache(item) for item in value]
        return value

    payload = to_json_object(
        without_cache(
            {
                "system": system,
                "messages": messages,
                "tools": tools_payload(request, names),
            }
        )
    )
    return sha256(dumps_json(payload).encode("utf-8")).hexdigest()
