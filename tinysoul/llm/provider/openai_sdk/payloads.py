"""Request payload mapping for OpenAI SDK shaped providers."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Protocol

from tinysoul.infra.json import JsonObject
from tinysoul.llm.adapter_types import ProviderApiStyle
from tinysoul.llm.message_rendering import (
    MessageContentRenderer,
    RenderedContentPart,
    RenderedImage,
    RenderedImageUrl,
    RenderedText,
)
from tinysoul.llm.messages import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.tools import (
    ToolCallIdMapper,
    ToolCallRecord,
    ToolResultStatus,
    ToolSpec,
    ToolUse,
)

from ..base import ProviderError, ProviderErrorKind, ProviderRequest
from .tool_names import ProviderToolNameMap


class OpenAIAdapterBehaviorProtocol(Protocol):
    """Behavior surface needed while mapping SDK request payloads."""

    def validate_tool_choice(self, request: ProviderRequest) -> None:
        ...

    def tool_payload(
        self,
        tool: ToolSpec,
        *,
        api_style: ProviderApiStyle,
    ) -> dict[str, object]:
        ...

    def tool_choice_payload(
        self,
        request: ProviderRequest,
        *,
        api_style: ProviderApiStyle,
    ) -> object | None:
        ...

    def include_chat_tool_result_name(self) -> bool:
        ...

    def chat_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> str | None:
        ...

    def responses_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> tuple[JsonObject, ...]:
        ...


def to_responses_input(
    request: ProviderRequest,
    *,
    behavior: OpenAIAdapterBehaviorProtocol,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
    name_map: ProviderToolNameMap,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    replay_plan = _tool_replay_plan(request.messages.messages)
    for index, message in enumerate(request.messages.messages):
        if isinstance(message, ToolResultMessage):
            if request.tool_use is ToolUse.DISABLED:
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
            if index not in replay_plan.result_indices:
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
                for reasoning_item in behavior.responses_input_reasoning(
                    message,
                    request.model.adapter_options.values,
                ):
                    items.append({key: value for key, value in reasoning_item.items()})
            rendered = renderer.render(message.parts)
            if message.parts:
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
    return items


def to_chat_messages(
    request: ProviderRequest,
    *,
    behavior: OpenAIAdapterBehaviorProtocol,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
    name_map: ProviderToolNameMap,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    replay_plan = _tool_replay_plan(request.messages.messages)
    for index, message in enumerate(request.messages.messages):
        if isinstance(message, ToolResultMessage):
            if request.tool_use is ToolUse.DISABLED:
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
            if index not in replay_plan.result_indices:
                continue
            items.append(
                to_chat_tool_result(
                    message,
                    behavior=behavior,
                    renderer=renderer,
                    id_mapper=id_mapper,
                    name_map=name_map,
                )
            )
            continue
        rendered = renderer.render(message.parts)
        reasoning_content = None
        replayed_tool_calls: tuple[ToolCallRecord, ...] = ()
        if isinstance(message, AssistantMessage):
            reasoning_content = behavior.chat_input_reasoning(
                message,
                request.model.adapter_options.values,
            )
            replayed_tool_calls = (
                ()
                if request.tool_use is ToolUse.DISABLED
                or index not in replay_plan.assistant_indices
                else message.tool_calls
            )
            if message.tool_calls and not replayed_tool_calls:
                reasoning_content = None
            if (
                not message.parts
                and reasoning_content is None
                and not replayed_tool_calls
            ):
                continue
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
    api_style: ProviderApiStyle,
    behavior: OpenAIAdapterBehaviorProtocol,
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
    behavior.validate_tool_choice(request)
    kwargs["tools"] = [
        behavior.tool_payload(
            name_map.to_provider_tool(tool),
            api_style=api_style,
        )
        for tool in tools
    ]
    tool_choice = behavior.tool_choice_payload(request, api_style=api_style)
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    elif request.tool_use is ToolUse.REQUIRED:
        kwargs["tool_choice"] = "required"


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
    behavior: OpenAIAdapterBehaviorProtocol,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
    name_map: ProviderToolNameMap,
) -> dict[str, object]:
    item: dict[str, object] = {
        "role": "tool",
        "tool_call_id": id_mapper.to_provider_id(message.call_id),
        "content": tool_result_content(message, renderer=renderer),
    }
    if behavior.include_chat_tool_result_name():
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


def tool_result_content(
    message: ToolResultMessage,
    *,
    renderer: MessageContentRenderer,
) -> str:
    rendered = renderer.render(message.parts)
    if isinstance(rendered, str):
        if message.status is ToolResultStatus.OK:
            return rendered
        return f"status: {message.status.value}\n\n{rendered}"
    text_parts: list[str] = []
    for part in rendered:
        if isinstance(part, RenderedText):
            text_parts.append(part.text)
            continue
        raise ProviderError(
            "ToolResultMessage can only be rendered as text content",
            kind=ProviderErrorKind.CONFIG,
        )
    text = "\n\n".join(text_parts)
    if message.status is ToolResultStatus.OK:
        return text
    return f"status: {message.status.value}\n\n{text}"


def tool_result_text(
    message: ToolResultMessage,
    *,
    renderer: MessageContentRenderer,
) -> str:
    """Render a tool result as ordinary context when native tools are disabled."""

    return (
        f"Tool result for {message.tool_name}:\n"
        f"{tool_result_content(message, renderer=renderer)}"
    )


@dataclass(frozen=True)
class _ToolReplayPlan:
    """Indices of complete, ordered provider-native tool turns."""

    assistant_indices: frozenset[int]
    result_indices: frozenset[int]


def _tool_replay_plan(messages: tuple[Message, ...]) -> _ToolReplayPlan:
    assistant_indices: set[int] = set()
    result_indices: set[int] = set()
    for index, message in enumerate(messages):
        if not isinstance(message, AssistantMessage) or not message.tool_calls:
            continue
        calls_by_id: dict[str, ToolCallRecord] = {}
        duplicate_call_id = False
        for call in message.tool_calls:
            if call.id in calls_by_id:
                duplicate_call_id = True
                break
            calls_by_id[call.id] = call
        if duplicate_call_id:
            continue

        candidate_results: list[tuple[int, ToolResultMessage]] = []
        cursor = index + 1
        while cursor < len(messages):
            candidate = messages[cursor]
            if not isinstance(candidate, ToolResultMessage):
                break
            candidate_results.append((cursor, candidate))
            cursor += 1
        if len(candidate_results) != len(calls_by_id):
            continue
        result_by_id: dict[str, tuple[int, ToolResultMessage]] = {}
        for result_index, result in candidate_results:
            if result.call_id in result_by_id:
                break
            result_by_id[result.call_id] = (result_index, result)
        if len(result_by_id) != len(calls_by_id):
            continue
        if set(result_by_id) != set(calls_by_id):
            continue
        if any(
            calls_by_id[call_id].name != result.tool_name
            for call_id, (_, result) in result_by_id.items()
        ):
            continue
        assistant_indices.add(index)
        result_indices.update(result_index for result_index, _ in candidate_results)
    return _ToolReplayPlan(
        assistant_indices=frozenset(assistant_indices),
        result_indices=frozenset(result_indices),
    )


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
    "OpenAIAdapterBehaviorProtocol",
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
