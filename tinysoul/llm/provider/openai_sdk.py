"""OpenAI SDK backed provider adapter foundations."""

from __future__ import annotations

import base64
from collections.abc import Mapping
import json
from typing import Protocol, cast

from openai import APIConnectionError, APIError, APIStatusError, OpenAI

from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
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
from tinysoul.llm.models import ModelCapability, ProviderOptions, ProviderRequestOverrides
from tinysoul.llm.reasoning import Reasoning, ReasoningKeep
from tinysoul.llm.responses import AnswerFormat, RawResponse
from tinysoul.llm.tools import (
    DefaultToolCallIdMapper,
    ToolCallRecord,
    ToolCallIdMapper,
    ToolKind,
    ToolResultStatus,
    ToolSelection,
    ToolUse,
    ToolSpec,
)
from tinysoul.infra.json import JsonObject, to_json_object

from .base import ProviderError, ProviderErrorKind, ProviderRequest


class OpenAIResponsesClient(Protocol):
    """Narrow SDK surface used by the Responses adapter."""

    def create(self, **kwargs: object) -> object:
        ...


class OpenAIChatCompletionsClient(Protocol):
    """Narrow SDK surface used by the Chat Completions adapter."""

    def create(self, **kwargs: object) -> object:
        ...


class ModelDumpable(Protocol):
    """Object that can expose a JSON-safe mapping."""

    def model_dump(self, *, mode: str) -> object:
        ...


class OpenAIAdapterBehavior:
    """Supplier-specific behavior for OpenAI SDK shaped APIs."""

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
    ) -> None:
        if not options:
            return
        key = next(iter(options))
        raise ProviderError(
            f"Unsupported provider option: {key}",
            kind=ProviderErrorKind.CONFIG,
        )

    def validate_tools(self, request: ProviderRequest) -> None:
        return

    def apply_prompt_cache(
        self,
        kwargs: dict[str, object],
        request: ProviderRequest,
    ) -> None:
        return

    def chat_output_reasoning(self, message: object) -> Reasoning | None:
        content = _chat_reasoning_content(message)
        if content is None:
            return None
        return Reasoning(content=content, summary=content)

    def responses_output_reasoning(self, response: object) -> Reasoning | None:
        summary = _responses_reasoning_summary(response)
        encrypted_items = _responses_encrypted_reasoning_items(response)
        if summary is None and not encrypted_items:
            return None
        return Reasoning(summary=summary, encrypted_items=encrypted_items)

    def chat_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> str | None:
        return None

    def responses_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> tuple[JsonObject, ...]:
        return ()


class OpenAIResponsesAdapter:
    """Reusable adapter for OpenAI Responses shaped APIs."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        responses: OpenAIResponsesClient | None = None,
        behavior: OpenAIAdapterBehavior | None = None,
        id_mapper: ToolCallIdMapper | None = None,
    ) -> None:
        self.provider_id = provider.id
        self._behavior = behavior or OpenAIAdapterBehavior()
        self._id_mapper = id_mapper or DefaultToolCallIdMapper()
        if responses is None:
            self._client: OpenAIResponsesClient = cast(
                OpenAIResponsesClient,
                OpenAI(
                    api_key=api_key,
                    base_url=provider.base_url,
                ).responses,
            )
        else:
            self._client = responses
        self._renderer = MessageContentRenderer()

    def invoke(self, request: ProviderRequest) -> RawResponse:
        provider_options = _provider_options(request.provider_options)
        kwargs = _common_create_kwargs(request)
        self._behavior.validate_tools(request)
        self._behavior.apply_prompt_cache(kwargs, request)
        kwargs["input"] = _to_responses_input(
            request,
            behavior=self._behavior,
            renderer=self._renderer,
            id_mapper=self._id_mapper,
        )
        _apply_tools_kwargs(kwargs, request, api_style=ProviderApiStyle.OPENAI_RESPONSES)
        if _uses_native_json_output(request):
            kwargs["text"] = {"format": {"type": "json_object"}}
        self._behavior.apply_options(kwargs, provider_options)

        try:
            response = self._client.create(**kwargs)
        except Exception as exc:
            raise _provider_error(exc) from exc

        return RawResponse(
            answer_text=_responses_text(response),
            model_id=request.model.id,
            provider_id=self.provider_id,
            tool_calls=_responses_tool_calls(response, id_mapper=self._id_mapper),
            reasoning=self._behavior.responses_output_reasoning(response),
            usage=_model_dump_mapping(_get_attr(response, "usage")),
            metadata=_response_metadata(response),
            provider_payload=to_json_object(_model_dump_mapping(response)),
        )


class OpenAICompatibleChatAdapter:
    """Reusable adapter for OpenAI-compatible Chat Completions APIs."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        completions: OpenAIChatCompletionsClient | None = None,
        behavior: OpenAIAdapterBehavior | None = None,
        id_mapper: ToolCallIdMapper | None = None,
    ) -> None:
        self.provider_id = provider.id
        self._behavior = behavior or OpenAIAdapterBehavior()
        self._id_mapper = id_mapper or DefaultToolCallIdMapper()
        if completions is None:
            self._client: OpenAIChatCompletionsClient = cast(
                OpenAIChatCompletionsClient,
                OpenAI(
                    api_key=api_key,
                    base_url=provider.base_url,
                ).chat.completions,
            )
        else:
            self._client = completions
        self._renderer = MessageContentRenderer()

    def invoke(self, request: ProviderRequest) -> RawResponse:
        provider_options = _provider_options(request.provider_options)
        kwargs = _common_create_kwargs(request)
        self._behavior.validate_tools(request)
        self._behavior.apply_prompt_cache(kwargs, request)
        kwargs["messages"] = _to_chat_messages(
            request,
            behavior=self._behavior,
            renderer=self._renderer,
            id_mapper=self._id_mapper,
        )
        _apply_tools_kwargs(kwargs, request, api_style=ProviderApiStyle.OPENAI_CHAT)
        max_output_tokens = kwargs.pop("max_output_tokens", None)
        if max_output_tokens is not None:
            kwargs["max_completion_tokens"] = max_output_tokens
        if _uses_native_json_output(request):
            kwargs["response_format"] = {"type": "json_object"}
        self._behavior.apply_options(kwargs, provider_options)

        try:
            response = self._client.create(**kwargs)
        except Exception as exc:
            raise _provider_error(exc) from exc

        message = _first_choice_message(response)
        return RawResponse(
            answer_text=_message_text(message),
            model_id=request.model.id,
            provider_id=self.provider_id,
            tool_calls=_chat_tool_calls(message, id_mapper=self._id_mapper),
            reasoning=self._behavior.chat_output_reasoning(message),
            usage=_model_dump_mapping(_get_attr(response, "usage")),
            metadata=_response_metadata(response),
            provider_payload=to_json_object(_model_dump_mapping(response)),
        )


def _common_create_kwargs(request: ProviderRequest) -> dict[str, object]:
    overrides = _request_overrides(request.provider_options)
    kwargs: dict[str, object] = {"model": request.model.provider_model}
    temperature = _effective_temperature(request, overrides=overrides)
    if temperature is not None:
        kwargs["temperature"] = temperature
    max_output_tokens = _effective_max_output_tokens(request, overrides=overrides)
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens
    return kwargs


def _effective_temperature(
    request: ProviderRequest,
    *,
    overrides: ProviderRequestOverrides | None = None,
) -> float | None:
    resolved = overrides or _request_overrides(request.provider_options)
    return (
        resolved.temperature
        if resolved.temperature is not None
        else request.temperature
    )


def _effective_max_output_tokens(
    request: ProviderRequest,
    *,
    overrides: ProviderRequestOverrides | None = None,
) -> int | None:
    resolved = overrides or _request_overrides(request.provider_options)
    return (
        resolved.max_output_tokens
        if resolved.max_output_tokens is not None
        else request.max_output_tokens
    )


def _request_overrides(
    options: Mapping[str, object] | None,
) -> ProviderRequestOverrides:
    try:
        return ProviderOptions(options or {}).request_overrides()
    except (TypeError, ValueError) as exc:
        raise ProviderError(str(exc), kind=ProviderErrorKind.CONFIG) from exc


def _provider_options(options: Mapping[str, object] | None) -> dict[str, object]:
    try:
        return ProviderOptions(options or {}).provider_values()
    except (TypeError, ValueError) as exc:
        raise ProviderError(str(exc), kind=ProviderErrorKind.CONFIG) from exc


def _uses_native_json_output(request: ProviderRequest) -> bool:
    return request.answer_format is AnswerFormat.JSON_OBJECT and request.model.supports(
        ModelCapability.JSON_OBJECT_OUTPUT
    )


def _to_responses_input(
    request: ProviderRequest,
    *,
    behavior: OpenAIAdapterBehavior,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for message in request.messages.messages:
        if isinstance(message, ToolResultMessage):
            items.append(
                _to_responses_tool_result(
                    message,
                    renderer=renderer,
                    id_mapper=id_mapper,
                )
            )
            continue
        if isinstance(message, AssistantMessage):
            for reasoning_item in behavior.responses_input_reasoning(
                message,
                request.provider_options,
            ):
                items.append({key: value for key, value in reasoning_item.items()})
            rendered = renderer.render(message.parts)
            if message.parts:
                items.append(
                    {
                        "role": "assistant",
                        "content": _to_responses_content(
                            rendered,
                            role="assistant",
                        ),
                    }
                )
            for tool_call in message.tool_calls:
                items.append(
                    _to_responses_function_call(tool_call, id_mapper=id_mapper)
                )
            continue
        rendered = renderer.render(message.parts)
        items.append(
            {
                "role": _responses_role(message),
                "content": _to_responses_content(
                    rendered,
                    role=_responses_role(message),
                ),
            }
        )
    return items


def _to_chat_messages(
    request: ProviderRequest,
    *,
    behavior: OpenAIAdapterBehavior,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for message in request.messages.messages:
        if isinstance(message, ToolResultMessage):
            items.append(
                _to_chat_tool_result(
                    message,
                    renderer=renderer,
                    id_mapper=id_mapper,
                )
            )
            continue
        rendered = renderer.render(message.parts)
        item: dict[str, object] = {
            "role": _chat_role(message),
            "content": _to_chat_content(rendered),
        }
        if isinstance(message, AssistantMessage):
            reasoning_content = behavior.chat_input_reasoning(
                message,
                request.provider_options,
            )
            if reasoning_content is not None:
                item["reasoning_content"] = reasoning_content
            if message.tool_calls:
                item["tool_calls"] = [
                    _to_chat_tool_call(tool_call, id_mapper=id_mapper)
                    for tool_call in message.tool_calls
                ]
        items.append(item)
    return items


def _to_chat_content(
    rendered: str | tuple[RenderedContentPart, ...],
) -> str | list[dict[str, object]]:
    if isinstance(rendered, str):
        return rendered
    return [_to_chat_part(part) for part in rendered]


def _to_responses_content(
    rendered: str | tuple[RenderedContentPart, ...],
    *,
    role: str,
) -> list[dict[str, object]]:
    if isinstance(rendered, str):
        return [{"type": _responses_text_type(role), "text": rendered}]
    return [_to_responses_part(part, role=role) for part in rendered]


def _to_responses_part(
    part: RenderedContentPart,
    *,
    role: str,
) -> dict[str, object]:
    if isinstance(part, RenderedText):
        return {"type": _responses_text_type(role), "text": part.text}
    if isinstance(part, RenderedImageUrl):
        return {
            "type": "input_image",
            "image_url": part.url,
            "detail": "auto",
        }
    return {
        "type": "input_image",
        "image_url": _image_data_url(part),
        "detail": "auto",
    }


def _responses_text_type(role: str) -> str:
    if role == "assistant":
        return "output_text"
    return "input_text"


def _to_chat_part(part: RenderedContentPart) -> dict[str, object]:
    if isinstance(part, RenderedText):
        return {"type": "text", "text": part.text}
    if isinstance(part, RenderedImageUrl):
        return {"type": "image_url", "image_url": {"url": part.url}}
    return {"type": "image_url", "image_url": {"url": _image_data_url(part)}}


def _apply_tools_kwargs(
    kwargs: dict[str, object],
    request: ProviderRequest,
    *,
    api_style: ProviderApiStyle,
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
    kwargs["tools"] = [_to_provider_tool(tool) for tool in tools]
    tool_choice = _tool_choice(request.tool_scope.selection, api_style=api_style)
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    elif request.tool_use is ToolUse.REQUIRED:
        kwargs["tool_choice"] = "required"

def _tool_choice(
    selection: ToolSelection,
    *,
    api_style: ProviderApiStyle,
) -> object | None:
    if selection.forced_name is None:
        return None
    if api_style is ProviderApiStyle.OPENAI_RESPONSES:
        return {
            "type": "function",
            "name": selection.forced_name,
        }
    return {
        "type": "function",
        "function": {"name": selection.forced_name},
    }


def _to_provider_tool(tool: ToolSpec) -> dict[str, object]:
    function: dict[str, object] = {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }
    if tool.strict is not None:
        function["strict"] = tool.strict
    return {
        "type": "function",
        "function": function,
    }


def _to_chat_tool_call(
    tool_call: ToolCallRecord,
    *,
    id_mapper: ToolCallIdMapper,
) -> dict[str, object]:
    return {
        "id": id_mapper.to_provider_id(tool_call.id),
        "type": "function",
        "function": {
            "name": tool_call.name,
            "arguments": json.dumps(
                tool_call.arguments,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    }


def _to_chat_tool_result(
    message: ToolResultMessage,
    *,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
) -> dict[str, object]:
    return {
        "role": "tool",
        "tool_call_id": id_mapper.to_provider_id(message.call_id),
        "content": _tool_result_content(message, renderer=renderer),
    }


def _to_responses_function_call(
    tool_call: ToolCallRecord,
    *,
    id_mapper: ToolCallIdMapper,
) -> dict[str, object]:
    return {
        "type": "function_call",
        "call_id": id_mapper.to_provider_id(tool_call.id),
        "name": tool_call.name,
        "arguments": json.dumps(
            tool_call.arguments,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }


def _to_responses_tool_result(
    message: ToolResultMessage,
    *,
    renderer: MessageContentRenderer,
    id_mapper: ToolCallIdMapper,
) -> dict[str, object]:
    return {
        "type": "function_call_output",
        "call_id": id_mapper.to_provider_id(message.call_id),
        "output": _tool_result_content(message, renderer=renderer),
    }


def _tool_result_content(
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
    text = "\n\n".join(text_parts)
    if message.status is ToolResultStatus.OK:
        return text
    return f"status: {message.status.value}\n\n{text}"


def _responses_role(message: Message) -> str:
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


def _chat_role(message: Message) -> str:
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


def provider_reasoning_keep(
    options: Mapping[str, object] | None,
    *,
    provider: str,
) -> ReasoningKeep:
    if options is None:
        return ReasoningKeep.NONE
    value = options.get("reasoning_keep")
    if value is None:
        return ReasoningKeep.NONE
    if not isinstance(value, str):
        raise ProviderError(
            f"{provider} reasoning_keep must be a string",
            kind=ProviderErrorKind.CONFIG,
        )
    try:
        return ReasoningKeep(value)
    except ValueError as exc:
        raise ProviderError(
            f"{provider} reasoning_keep must be 'none', 'content', or 'encrypted'",
            kind=ProviderErrorKind.CONFIG,
        ) from exc


def _image_data_url(part: RenderedImage) -> str:
    encoded = base64.b64encode(part.data).decode("ascii")
    return f"data:{part.mime_type};base64,{encoded}"


def _provider_error(error: Exception) -> ProviderError:
    if isinstance(error, ProviderError):
        return error
    if isinstance(error, APIStatusError):
        if error.status_code in {401, 403}:
            return ProviderError(str(error), kind=ProviderErrorKind.AUTH)
        if error.status_code in {408, 409, 429, 500, 502, 503, 504}:
            return ProviderError(str(error), kind=ProviderErrorKind.TRANSIENT)
        if error.status_code == 400:
            return ProviderError(str(error), kind=ProviderErrorKind.CONFIG)
        return ProviderError(str(error), kind=ProviderErrorKind.UNKNOWN)
    if isinstance(error, (APIConnectionError, APIError, TimeoutError)):
        return ProviderError(str(error), kind=ProviderErrorKind.TRANSIENT)
    return ProviderError(str(error), kind=ProviderErrorKind.UNKNOWN)


def _responses_text(response: object) -> str:
    output_text = _get_attr(response, "output_text")
    if isinstance(output_text, str):
        return output_text
    output = _get_attr(response, "output")
    if isinstance(output, list):
        texts: list[str] = []
        for item in output:
            content = _get_attr(item, "content")
            if isinstance(content, list):
                for part in content:
                    text = _get_attr(part, "text")
                    if isinstance(text, str):
                        texts.append(text)
        return "\n".join(texts)
    return ""


def _responses_tool_calls(
    response: object,
    *,
    id_mapper: ToolCallIdMapper,
) -> tuple[ToolCallRecord, ...]:
    output = _get_attr(response, "output")
    if not isinstance(output, list):
        return ()
    records: list[ToolCallRecord] = []
    for index, item in enumerate(output):
        item_type = _get_attr(item, "type")
        if item_type != "function_call":
            continue
        name = _get_attr(item, "name")
        call_id = _get_attr(item, "call_id")
        arguments = _get_attr(item, "arguments")
        if not isinstance(name, str) or not isinstance(call_id, str):
            continue
        parsed_arguments = _parse_tool_arguments(arguments)
        records.append(
            ToolCallRecord(
                id=id_mapper.to_tinysoul_id(
                    call_id,
                    index=index,
                    tool_name=name,
                ),
                name=name,
                arguments=parsed_arguments,
            )
        )
    return tuple(records)


def _responses_reasoning_summary(response: object) -> str | None:
    output = _get_attr(response, "output")
    if not isinstance(output, list):
        return None
    texts: list[str] = []
    for item in output:
        item_type = _get_attr(item, "type")
        if item_type != "reasoning":
            continue
        _append_text_parts(texts, _get_attr(item, "summary"))
        _append_text_parts(texts, _get_attr(item, "content"))
    return "\n".join(texts) if texts else None


def _responses_encrypted_reasoning_items(response: object) -> tuple[JsonObject, ...]:
    output = _get_attr(response, "output")
    if not isinstance(output, list):
        return ()
    items: list[JsonObject] = []
    for item in output:
        item_type = _get_attr(item, "type")
        encrypted_content = _get_attr(item, "encrypted_content")
        if item_type != "reasoning" or not isinstance(encrypted_content, str):
            continue
        items.append(to_json_object(_model_dump_mapping(item)))
    return tuple(items)


def _append_text_parts(texts: list[str], value: object) -> None:
    if isinstance(value, str):
        texts.append(value)
        return
    if not isinstance(value, list):
        return
    for part in value:
        if isinstance(part, str):
            texts.append(part)
            continue
        text = _get_attr(part, "text")
        if isinstance(text, str):
            texts.append(text)


def _first_choice_message(response: object) -> object:
    choices = _get_attr(response, "choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("Provider response has no choices", kind=ProviderErrorKind.PARSE)
    return _get_attr(choices[0], "message")


def _message_text(message: object) -> str:
    content = _get_attr(message, "content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            text = _get_attr(part, "text")
            if isinstance(text, str):
                texts.append(text)
        return "\n".join(texts)
    return ""


def _chat_tool_calls(
    message: object,
    *,
    id_mapper: ToolCallIdMapper,
) -> tuple[ToolCallRecord, ...]:
    tool_calls = _get_attr(message, "tool_calls")
    if not isinstance(tool_calls, list):
        return ()
    records: list[ToolCallRecord] = []
    for index, item in enumerate(tool_calls):
        item_type = _get_attr(item, "type")
        if item_type not in {None, "function"}:
            continue
        call_id = _get_attr(item, "id")
        function = _get_attr(item, "function")
        name = _get_attr(function, "name")
        arguments = _get_attr(function, "arguments")
        if not isinstance(call_id, str) or not isinstance(name, str):
            continue
        records.append(
            ToolCallRecord(
                id=id_mapper.to_tinysoul_id(
                    call_id,
                    index=index,
                    tool_name=name,
                ),
                name=name,
                arguments=_parse_tool_arguments(arguments),
            )
        )
    return tuple(records)


def _parse_tool_arguments(value: object) -> JsonObject:
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


def _chat_reasoning_content(message: object) -> str | None:
    value = _get_attr(message, "reasoning_content")
    if isinstance(value, str):
        return value
    value = _get_attr(message, "reasoning")
    if isinstance(value, str):
        return value
    return None


def _response_metadata(response: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in ("id", "model", "service_tier", "system_fingerprint", "status"):
        value = _get_attr(response, key)
        if isinstance(value, str):
            result[key] = value
    return result


def _model_dump_mapping(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    model_dump = _get_attr(value, "model_dump")
    if callable(model_dump):
        dumped = cast(ModelDumpable, value).model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    return {}


def _get_attr(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)
