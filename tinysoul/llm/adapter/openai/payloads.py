"""Request payload mapping for OpenAI SDK shaped providers."""

from __future__ import annotations

import base64
import json
from typing import Protocol

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.execution.message_rendering import (
    MessageContentRenderer,
    RenderedContentPart,
    RenderedImage,
    RenderedImageUrl,
    RenderedText,
)
from tinysoul.llm.protocol.adapter_types import ApiMode
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.protocol.tools import (
    ToolCallIdMapper,
    ToolCallRecord,
    ToolSpec,
    ToolUse,
)

from ..base import ProviderError, ProviderErrorKind, ProviderRequest
from ..common import cache_boundaries, cache_ttl
from ..history import (
    assistant_context_parts,
    tool_replay_plan,
    tool_result_content,
    tool_result_text,
)
from ..tool_names import ProviderToolNameMap


class OpenAIPayloadHooks(Protocol):
    """Behavior surface needed while mapping SDK request payloads."""

    def tool_payload(
        self,
        tool: ToolSpec,
        *,
        api_mode: ApiMode,
    ) -> dict[str, object]: ...

    def tool_choice_payload(
        self,
        request: ProviderRequest,
        *,
        api_mode: ApiMode,
    ) -> object | None: ...

    def include_chat_tool_result_name(self) -> bool: ...

    def chat_input_reasoning(
        self,
        message: Message,
        request: ProviderRequest,
    ) -> str | None: ...

    def responses_input_reasoning(
        self,
        message: Message,
        request: ProviderRequest,
    ) -> tuple[JsonObject, ...]: ...


def to_responses_input(
    request: ProviderRequest,
    *,
    adapter: OpenAIPayloadHooks,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
    name_map: ProviderToolNameMap,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    cuts: list[int] = []
    replay_plan = tool_replay_plan(request.messages.messages)
    for index, message in enumerate(request.messages.messages):
        cuts.append(len(items))
        if isinstance(message, ToolResultMessage):
            if (
                request.tool_use is ToolUse.DISABLED
                or index not in replay_plan.result_indices
            ):
                items.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": tool_result_text(
                                    message,
                                    renderer=renderer,
                                ),
                            }
                        ],
                    }
                )
                continue
            items.append(
                to_responses_tool_result(
                    message,
                    renderer=renderer,
                    id_mapper=id_mapper,
                )
            )
            continue
        if isinstance(message, AssistantMessage):
            replayed_tool_calls = (
                ()
                if request.tool_use is ToolUse.DISABLED
                or index not in replay_plan.assistant_indices
                else message.tool_calls
            )
            if not message.tool_calls or replayed_tool_calls:
                native = adapter.responses_input_reasoning(
                    message,
                    request,
                )
                expected_calls = {
                    id_mapper.to_provider_id(call.id): name_map.to_provider_name(
                        call.name
                    )
                    for call in replayed_tool_calls
                }
                native_calls = {
                    item.get("call_id"): item.get("name")
                    for item in native
                    if item.get("type") == "function_call"
                }
                if native and native_calls == expected_calls:
                    items.extend(dict(to_json_object(item)) for item in native)
                    continue
            parts = assistant_context_parts(
                message, native_calls=bool(replayed_tool_calls)
            )
            rendered = renderer.render(parts)
            if parts:
                items.append(
                    {
                        "role": "assistant",
                        "content": to_responses_content(
                            rendered,
                            role="assistant",
                        ),
                    }
                )
            for tool_call in replayed_tool_calls:
                items.append(
                    to_responses_function_call(
                        tool_call,
                        id_mapper=id_mapper,
                        name_map=name_map,
                    )
                )
            continue
        rendered = renderer.render(message.parts)
        items.append(
            {
                "role": responses_role(message),
                "content": to_responses_content(
                    rendered,
                    role=responses_role(message),
                ),
            }
        )
    cuts.append(len(items))
    _mark_cache_boundary(items, cuts, request, api_mode=ApiMode.OPENAI_RESPONSES)
    return items


def to_chat_messages(
    request: ProviderRequest,
    *,
    adapter: OpenAIPayloadHooks,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
    name_map: ProviderToolNameMap,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    cuts: list[int] = []
    replay_plan = tool_replay_plan(request.messages.messages)
    for index, message in enumerate(request.messages.messages):
        cuts.append(len(items))
        if isinstance(message, ToolResultMessage):
            if (
                request.tool_use is ToolUse.DISABLED
                or index not in replay_plan.result_indices
            ):
                items.append(
                    {
                        "role": "user",
                        "content": tool_result_text(
                            message,
                            renderer=renderer,
                        ),
                    }
                )
                continue
            items.append(
                to_chat_tool_result(
                    message,
                    adapter=adapter,
                    renderer=renderer,
                    id_mapper=id_mapper,
                    name_map=name_map,
                )
            )
            continue
        parts = message.parts
        reasoning_content = None
        replayed_tool_calls: tuple[ToolCallRecord, ...] = ()
        if isinstance(message, AssistantMessage):
            reasoning_content = adapter.chat_input_reasoning(
                message,
                request,
            )
            replayed_tool_calls = (
                ()
                if request.tool_use is ToolUse.DISABLED
                or index not in replay_plan.assistant_indices
                else message.tool_calls
            )
            if message.tool_calls and not replayed_tool_calls:
                reasoning_content = None
            parts = assistant_context_parts(
                message, native_calls=bool(replayed_tool_calls)
            )
            if not parts and reasoning_content is None and not replayed_tool_calls:
                continue
        rendered = renderer.render(parts)
        item: dict[str, object] = {
            "role": chat_role(message),
            "content": to_chat_content(rendered),
        }
        if isinstance(message, AssistantMessage):
            if reasoning_content is not None:
                item["reasoning_content"] = reasoning_content
            if replayed_tool_calls:
                item["tool_calls"] = [
                    to_chat_tool_call(
                        tool_call,
                        id_mapper=id_mapper,
                        name_map=name_map,
                    )
                    for tool_call in replayed_tool_calls
                ]
        items.append(item)
    cuts.append(len(items))
    _mark_cache_boundary(items, cuts, request, api_mode=ApiMode.OPENAI_CHAT)
    return items


def to_chat_content(
    rendered: str | tuple[RenderedContentPart, ...],
) -> str | list[dict[str, object]]:
    if isinstance(rendered, str):
        return rendered
    return [to_chat_part(part) for part in rendered]


def to_responses_content(
    rendered: str | tuple[RenderedContentPart, ...],
    *,
    role: str,
) -> list[dict[str, object]]:
    if isinstance(rendered, str):
        return [{"type": responses_text_type(role), "text": rendered}]
    return [to_responses_part(part, role=role) for part in rendered]


def to_responses_part(
    part: RenderedContentPart,
    *,
    role: str,
) -> dict[str, object]:
    if isinstance(part, RenderedText):
        return {"type": responses_text_type(role), "text": part.text}
    if isinstance(part, RenderedImageUrl):
        return {
            "type": "input_image",
            "image_url": part.url,
            "detail": "auto",
        }
    return {
        "type": "input_image",
        "image_url": image_data_url(part),
        "detail": "auto",
    }


def responses_text_type(role: str) -> str:
    if role == "assistant":
        return "output_text"
    return "input_text"


def to_chat_part(part: RenderedContentPart) -> dict[str, object]:
    if isinstance(part, RenderedText):
        return {"type": "text", "text": part.text}
    if isinstance(part, RenderedImageUrl):
        return {"type": "image_url", "image_url": {"url": part.url}}
    return {"type": "image_url", "image_url": {"url": image_data_url(part)}}


def apply_tools_kwargs(
    kwargs: dict[str, object],
    request: ProviderRequest,
    *,
    api_mode: ApiMode,
    adapter: OpenAIPayloadHooks,
    name_map: ProviderToolNameMap,
) -> None:
    if (
        request.tool_scope.selection.forced_name is not None
        and request.tool_use is not ToolUse.REQUIRED
    ):
        raise ProviderError(
            "Forced tool selection requires required tool use",
            kind=ProviderErrorKind.CONFIG,
        )
    if request.tool_use is ToolUse.DISABLED:
        return
    tools = request.tool_scope.visible_tools()
    if not tools:
        return
    kwargs["tools"] = [
        adapter.tool_payload(
            name_map.to_provider_tool(tool),
            api_mode=api_mode,
        )
        for tool in tools
    ]
    tool_choice = adapter.tool_choice_payload(request, api_mode=api_mode)
    policy = request.model.adapter_options.values.get("tool_choice_policy")
    if policy == "auto":
        tool_choice = "auto"
    elif policy == "omit":
        tool_choice = None
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice


def function_payload(tool: ToolSpec) -> dict[str, object]:
    function: dict[str, object] = {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }
    if tool.strict is not None:
        function["strict"] = tool.strict
    return function


def to_chat_tool(tool: ToolSpec) -> dict[str, object]:
    return {
        "type": "function",
        "function": function_payload(tool),
    }


def to_responses_tool(tool: ToolSpec) -> dict[str, object]:
    return {
        "type": "function",
        **function_payload(tool),
    }


def to_chat_tool_call(
    tool_call: ToolCallRecord,
    *,
    id_mapper: ToolCallIdMapper,
    name_map: ProviderToolNameMap,
) -> dict[str, object]:
    return {
        "id": id_mapper.to_provider_id(tool_call.id),
        "type": "function",
        "function": {
            "name": name_map.to_provider_name(tool_call.name),
            "arguments": json.dumps(
                tool_call.arguments,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    }


def to_chat_tool_result(
    message: ToolResultMessage,
    *,
    adapter: OpenAIPayloadHooks,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
    name_map: ProviderToolNameMap,
) -> dict[str, object]:
    item: dict[str, object] = {
        "role": "tool",
        "tool_call_id": id_mapper.to_provider_id(message.call_id),
        "content": tool_result_content(message, renderer=renderer),
    }
    if adapter.include_chat_tool_result_name():
        item["name"] = name_map.to_provider_name(message.tool_name)
    return item


def to_responses_function_call(
    tool_call: ToolCallRecord,
    *,
    id_mapper: ToolCallIdMapper,
    name_map: ProviderToolNameMap,
) -> dict[str, object]:
    return {
        "type": "function_call",
        "call_id": id_mapper.to_provider_id(tool_call.id),
        "name": name_map.to_provider_name(tool_call.name),
        "arguments": json.dumps(
            tool_call.arguments,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }


def to_responses_tool_result(
    message: ToolResultMessage,
    *,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
) -> dict[str, object]:
    return {
        "type": "function_call_output",
        "call_id": id_mapper.to_provider_id(message.call_id),
        "output": tool_result_content(message, renderer=renderer),
    }


def responses_role(message: Message) -> str:
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, UserMessage):
        return "user"
    if isinstance(message, AssistantMessage):
        return "assistant"
    raise ProviderError(
        "ToolResultMessage must be mapped as function_call_output",
        kind=ProviderErrorKind.CONFIG,
    )


def chat_role(message: Message) -> str:
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, UserMessage):
        return "user"
    if isinstance(message, AssistantMessage):
        return "assistant"
    raise ProviderError(
        "ToolResultMessage must be mapped as role=tool",
        kind=ProviderErrorKind.CONFIG,
    )


def image_data_url(part: RenderedImage) -> str:
    encoded = base64.b64encode(part.data).decode("ascii")
    return f"data:{part.mime_type};base64,{encoded}"


__all__ = [
    "OpenAIPayloadHooks",
    "apply_tools_kwargs",
    "chat_role",
    "function_payload",
    "image_data_url",
    "responses_role",
    "responses_text_type",
    "to_chat_content",
    "to_chat_messages",
    "to_chat_part",
    "to_chat_tool",
    "to_chat_tool_call",
    "to_chat_tool_result",
    "to_responses_content",
    "to_responses_function_call",
    "to_responses_input",
    "to_responses_part",
    "to_responses_tool",
    "to_responses_tool_result",
    "tool_result_content",
]


def _mark_cache_boundary(
    items: list[dict[str, object]],
    cuts: list[int],
    request: ProviderRequest,
    *,
    api_mode: ApiMode,
) -> None:
    marked: set[int] = set()
    for point in cache_boundaries(request):
        for item in reversed(items[: cuts[point.message_index + 1]]):
            responses_output = item.get("type") == "function_call_output"
            field = "output" if responses_output else "content"
            content = item.get(field)
            if isinstance(content, str) and content:
                text_block: dict[str, object] = {
                    "type": "input_text" if responses_output else "text",
                    "text": content,
                }
                content = [text_block]
                item[field] = content
            if not isinstance(content, list):
                continue
            block = next(
                (
                    part
                    for part in reversed(content)
                    if isinstance(part, dict)
                    and part.get("type")
                    in {
                        "text",
                        "image_url",
                        "input_text",
                        "input_image",
                        "input_file",
                        "output_text",
                    }
                ),
                None,
            )
            if block is None:
                continue
            marker: dict[str, object] = {"mode": "explicit"}
            if api_mode is ApiMode.OPENAI_RESPONSES:
                marker["ttl"] = cache_ttl(request, point, "30m")
            block["prompt_cache_breakpoint"] = marker
            marked.add(id(block))
            break
    limit = (
        3
        if request.model.adapter_options.values.get("prompt_cache_mode") == "implicit"
        else 4
    )
    if len(marked) > limit:
        raise ProviderError(
            "Too many explicit OpenAI cache boundaries", kind=ProviderErrorKind.CONFIG
        )
