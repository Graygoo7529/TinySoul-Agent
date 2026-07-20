"""Response parsing helpers for OpenAI SDK shaped providers."""

from __future__ import annotations

from collections.abc import Mapping
import json

from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.llm.tools import ToolCallIdMapper, ToolCallRecord
from tinysoul.llm.responses import ResponseStopReason

from ..base import ProviderError, ProviderErrorKind
from .common import get_attr, model_dump_mapping
from .tool_names import ProviderToolNameMap


def responses_text(response: object) -> str:
    output_text = get_attr(response, "output_text")
    if isinstance(output_text, str):
        return output_text
    output = get_attr(response, "output")
    if isinstance(output, list):
        texts: list[str] = []
        for item in output:
            content = get_attr(item, "content")
            if isinstance(content, list):
                for part in content:
                    text = get_attr(part, "text")
                    if isinstance(text, str):
                        texts.append(text)
        return "\n".join(texts)
    return ""


def responses_stop_reason(response: object) -> ResponseStopReason:
    status = get_attr(response, "status")
    if status == "completed":
        return ResponseStopReason.COMPLETE
    if status != "incomplete":
        return ResponseStopReason.UNKNOWN
    details = get_attr(response, "incomplete_details")
    reason = get_attr(details, "reason")
    if reason in {"max_output_tokens", "max_tokens"}:
        return ResponseStopReason.OUTPUT_LIMIT
    if reason in {"content_filter", "content_filtered"}:
        return ResponseStopReason.CONTENT_FILTER
    return ResponseStopReason.INCOMPLETE


def responses_tool_calls(
    response: object,
    *,
    id_mapper: ToolCallIdMapper,
    name_map: ProviderToolNameMap,
) -> tuple[ToolCallRecord, ...]:
    output = get_attr(response, "output")
    if not isinstance(output, list):
        return ()
    records: list[ToolCallRecord] = []
    for index, item in enumerate(output):
        item_type = get_attr(item, "type")
        if item_type != "function_call":
            continue
        name = get_attr(item, "name")
        call_id = get_attr(item, "call_id")
        arguments = get_attr(item, "arguments")
        if not isinstance(name, str) or not name:
            raise ProviderError(
                "Responses function call is missing a valid name",
                kind=ProviderErrorKind.PARSE,
            )
        if not isinstance(call_id, str) or not call_id:
            raise ProviderError(
                "Responses function call is missing a valid call_id",
                kind=ProviderErrorKind.PARSE,
            )
        tinysoul_name = name_map.to_tinysoul_name(name)
        parsed_arguments = parse_tool_arguments(arguments)
        records.append(
            ToolCallRecord(
                id=id_mapper.to_tinysoul_id(
                    call_id,
                    index=index,
                    tool_name=tinysoul_name,
                ),
                name=tinysoul_name,
                arguments=parsed_arguments,
            )
        )
    return tuple(records)


def responses_reasoning_summary(response: object) -> str | None:
    output = get_attr(response, "output")
    if not isinstance(output, list):
        return None
    texts: list[str] = []
    for item in output:
        item_type = get_attr(item, "type")
        if item_type != "reasoning":
            continue
        append_text_parts(texts, get_attr(item, "summary"))
        append_text_parts(texts, get_attr(item, "content"))
    return "\n".join(texts) if texts else None


def responses_encrypted_reasoning_items(response: object) -> tuple[JsonObject, ...]:
    output = get_attr(response, "output")
    if not isinstance(output, list):
        return ()
    items: list[JsonObject] = []
    for item in output:
        item_type = get_attr(item, "type")
        encrypted_content = get_attr(item, "encrypted_content")
        if item_type != "reasoning" or not isinstance(encrypted_content, str):
            continue
        items.append(to_json_object(model_dump_mapping(item)))
    return tuple(items)


def append_text_parts(texts: list[str], value: object) -> None:
    if isinstance(value, str):
        texts.append(value)
        return
    if not isinstance(value, list):
        return
    for part in value:
        if isinstance(part, str):
            texts.append(part)
            continue
        text = get_attr(part, "text")
        if isinstance(text, str):
            texts.append(text)


def first_choice_message(response: object) -> object:
    choices = get_attr(response, "choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("Provider response has no choices", kind=ProviderErrorKind.PARSE)
    return get_attr(choices[0], "message")


def chat_stop_reason(response: object) -> ResponseStopReason:
    choices = get_attr(response, "choices")
    if not isinstance(choices, list) or not choices:
        return ResponseStopReason.UNKNOWN
    reason = get_attr(choices[0], "finish_reason")
    if reason == "stop":
        return ResponseStopReason.COMPLETE
    if reason in {"tool_calls", "function_call"}:
        return ResponseStopReason.TOOL_CALLS
    if reason == "length":
        return ResponseStopReason.OUTPUT_LIMIT
    if reason == "content_filter":
        return ResponseStopReason.CONTENT_FILTER
    return ResponseStopReason.UNKNOWN


def message_text(message: object) -> str:
    content = get_attr(message, "content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            text = get_attr(part, "text")
            if isinstance(text, str):
                texts.append(text)
        return "\n".join(texts)
    return ""


def chat_tool_calls(
    message: object,
    *,
    id_mapper: ToolCallIdMapper,
    name_map: ProviderToolNameMap,
) -> tuple[ToolCallRecord, ...]:
    tool_calls = get_attr(message, "tool_calls")
    if not isinstance(tool_calls, list):
        return ()
    records: list[ToolCallRecord] = []
    for index, item in enumerate(tool_calls):
        item_type = get_attr(item, "type")
        if item_type not in {None, "function"}:
            raise ProviderError(
                f"Unsupported chat tool call type: {item_type}",
                kind=ProviderErrorKind.PARSE,
            )
        call_id = get_attr(item, "id")
        function = get_attr(item, "function")
        if function is None:
            raise ProviderError(
                "Chat tool call is missing function payload",
                kind=ProviderErrorKind.PARSE,
            )
        name = get_attr(function, "name")
        arguments = get_attr(function, "arguments")
        if not isinstance(call_id, str) or not call_id:
            raise ProviderError(
                "Chat tool call is missing a valid id",
                kind=ProviderErrorKind.PARSE,
            )
        if not isinstance(name, str) or not name:
            raise ProviderError(
                "Chat tool call function is missing a valid name",
                kind=ProviderErrorKind.PARSE,
            )
        tinysoul_name = name_map.to_tinysoul_name(name)
        records.append(
            ToolCallRecord(
                id=id_mapper.to_tinysoul_id(
                    call_id,
                    index=index,
                    tool_name=tinysoul_name,
                ),
                name=tinysoul_name,
                arguments=parse_tool_arguments(arguments),
            )
        )
    return tuple(records)


def parse_tool_arguments(value: object) -> JsonObject:
    if isinstance(value, Mapping):
        return to_json_object(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"Failed to parse tool call arguments: {exc}",
                kind=ProviderErrorKind.PARSE,
            ) from exc
        if not isinstance(parsed, Mapping):
            raise ProviderError(
                "Tool call arguments must parse to a JSON object",
                kind=ProviderErrorKind.PARSE,
            )
        return to_json_object(parsed)
    if value is None:
        return {}
    raise ProviderError(
        "Tool call arguments must be a JSON object or JSON string",
        kind=ProviderErrorKind.PARSE,
    )


def chat_reasoning_content(message: object) -> str | None:
    value = get_attr(message, "reasoning_content")
    if isinstance(value, str):
        return value
    value = get_attr(message, "reasoning")
    if isinstance(value, str):
        return value
    return None


__all__ = [
    "append_text_parts",
    "chat_reasoning_content",
    "chat_stop_reason",
    "chat_tool_calls",
    "first_choice_message",
    "message_text",
    "parse_tool_arguments",
    "responses_encrypted_reasoning_items",
    "responses_reasoning_summary",
    "responses_stop_reason",
    "responses_text",
    "responses_tool_calls",
]
