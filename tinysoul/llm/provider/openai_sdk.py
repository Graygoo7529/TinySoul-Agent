"""OpenAI SDK backed provider adapter foundations."""

from __future__ import annotations

import base64
from collections.abc import Mapping
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
from tinysoul.llm.messages import Message
from tinysoul.llm.models import ModelCapability
from tinysoul.llm.reasoning import Reasoning
from tinysoul.llm.responses import ModelResponse, ResponseContract
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
    ) -> None:
        self.provider_id = provider.id
        self._behavior = behavior or OpenAIAdapterBehavior()
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

    def invoke(self, request: ProviderRequest) -> ModelResponse:
        kwargs = _common_create_kwargs(request)
        kwargs["input"] = _to_responses_input(
            request,
            behavior=self._behavior,
            renderer=self._renderer,
        )
        if _uses_native_json_output(request):
            kwargs["text"] = {"format": {"type": "json_object"}}
        self._behavior.apply_options(kwargs, request.provider_options)

        try:
            response = self._client.create(**kwargs)
        except Exception as exc:
            raise _provider_error(exc) from exc

        return ModelResponse(
            answer=_responses_text(response),
            model_id=request.model.id,
            provider_id=self.provider_id,
            reasoning=self._behavior.responses_output_reasoning(response),
            usage=_model_dump_mapping(_get_attr(response, "usage")),
            metadata=_response_metadata(response),
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
    ) -> None:
        self.provider_id = provider.id
        self._behavior = behavior or OpenAIAdapterBehavior()
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

    def invoke(self, request: ProviderRequest) -> ModelResponse:
        kwargs = _common_create_kwargs(request)
        kwargs["messages"] = _to_chat_messages(
            request,
            behavior=self._behavior,
            renderer=self._renderer,
        )
        if request.max_output_tokens is not None:
            kwargs.pop("max_output_tokens", None)
            kwargs["max_completion_tokens"] = request.max_output_tokens
        if _uses_native_json_output(request):
            kwargs["response_format"] = {"type": "json_object"}
        self._behavior.apply_options(kwargs, request.provider_options)

        try:
            response = self._client.create(**kwargs)
        except Exception as exc:
            raise _provider_error(exc) from exc

        message = _first_choice_message(response)
        return ModelResponse(
            answer=_message_text(message),
            model_id=request.model.id,
            provider_id=self.provider_id,
            reasoning=self._behavior.chat_output_reasoning(message),
            usage=_model_dump_mapping(_get_attr(response, "usage")),
            metadata=_response_metadata(response),
        )


def _common_create_kwargs(request: ProviderRequest) -> dict[str, object]:
    kwargs: dict[str, object] = {"model": request.model.provider_model}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_output_tokens is not None:
        kwargs["max_output_tokens"] = request.max_output_tokens
    if request.prompt_cache is not None and request.model.supports(
        ModelCapability.PROMPT_CACHE
    ):
        kwargs["prompt_cache_key"] = request.prompt_cache.key
    return kwargs


def _uses_native_json_output(request: ProviderRequest) -> bool:
    return request.response_contract is ResponseContract.JSON_OBJECT and request.model.supports(
        ModelCapability.JSON_OBJECT_OUTPUT
    )


def _to_responses_input(
    request: ProviderRequest,
    *,
    behavior: OpenAIAdapterBehavior,
    renderer: MessageContentRenderer,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for message in request.messages.messages:
        for reasoning_item in behavior.responses_input_reasoning(
            message,
            request.provider_options,
        ):
            items.append({key: value for key, value in reasoning_item.items()})
        role = _responses_role(message)
        rendered = renderer.render(message.parts)
        items.append(
            {
                "role": role,
                "content": _to_responses_content(rendered),
            }
        )
    return items


def _to_chat_messages(
    request: ProviderRequest,
    *,
    behavior: OpenAIAdapterBehavior,
    renderer: MessageContentRenderer,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for message in request.messages.messages:
        rendered = renderer.render(message.parts)
        item: dict[str, object] = {
            "role": message.role.value,
            "content": _to_chat_content(rendered),
        }
        reasoning_content = behavior.chat_input_reasoning(
            message,
            request.provider_options,
        )
        if reasoning_content is not None:
            item["reasoning_content"] = reasoning_content
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
) -> list[dict[str, object]]:
    if isinstance(rendered, str):
        return [{"type": "input_text", "text": rendered}]
    return [_to_responses_part(part) for part in rendered]


def _to_responses_part(part: RenderedContentPart) -> dict[str, object]:
    if isinstance(part, RenderedText):
        return {"type": "input_text", "text": part.text}
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


def _to_chat_part(part: RenderedContentPart) -> dict[str, object]:
    if isinstance(part, RenderedText):
        return {"type": "text", "text": part.text}
    if isinstance(part, RenderedImageUrl):
        return {"type": "image_url", "image_url": {"url": part.url}}
    return {"type": "image_url", "image_url": {"url": _image_data_url(part)}}


def _responses_role(message: Message) -> str:
    if message.reasoning is not None and message.reasoning.content is not None:
        raise ProviderError(
            "OpenAI Responses input does not accept text reasoning content",
            kind=ProviderErrorKind.CONFIG,
        )
    return message.role.value


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
