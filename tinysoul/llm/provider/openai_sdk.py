"""OpenAI SDK backed provider adapters."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Protocol, cast

from openai import APIConnectionError, APIError, APIStatusError, OpenAI

from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
from tinysoul.llm.messages import (
    ImagePart,
    ImageUrlPart,
    Message,
    MessagePart,
    MessageRole,
    TextPart,
)
from tinysoul.llm.models import ModelCapability
from tinysoul.llm.responses import ModelResponse, ResponseContract

from .base import ProviderAdapter, ProviderError, ProviderErrorKind, ProviderRequest
from .registry import ProviderRegistry


class OpenAIResponsesClient(Protocol):
    """Narrow SDK surface used by the OpenAI Responses adapter."""

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


class OpenAIResponsesAdapter:
    """Provider adapter for the OpenAI Responses API."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        responses: OpenAIResponsesClient | None = None,
    ) -> None:
        self.provider_id = provider.id
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

    def invoke(self, request: ProviderRequest) -> ModelResponse:
        kwargs = _common_create_kwargs(request)
        kwargs["input"] = _to_responses_input(request)
        if _uses_native_json_output(request):
            kwargs["text"] = {"format": {"type": "json_object"}}
        _apply_provider_options(kwargs, request.provider_options)

        try:
            response = self._client.create(**kwargs)
        except Exception as exc:
            raise _provider_error(exc) from exc

        return ModelResponse(
            text=_responses_text(response),
            model_id=request.model.id,
            provider_id=self.provider_id,
            reasoning_text=_responses_reasoning_text(response),
            usage=_model_dump_mapping(_get_attr(response, "usage")),
            metadata=_response_metadata(response),
        )


class OpenAIChatCompletionsAdapter:
    """Provider adapter for OpenAI-compatible Chat Completions APIs."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        completions: OpenAIChatCompletionsClient | None = None,
    ) -> None:
        self.provider_id = provider.id
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

    def invoke(self, request: ProviderRequest) -> ModelResponse:
        kwargs = _common_create_kwargs(request)
        kwargs["messages"] = _to_chat_messages(request)
        if request.max_output_tokens is not None:
            kwargs.pop("max_output_tokens", None)
            kwargs["max_completion_tokens"] = request.max_output_tokens
        if _uses_native_json_output(request):
            kwargs["response_format"] = {"type": "json_object"}
        _apply_provider_options(kwargs, request.provider_options)

        try:
            response = self._client.create(**kwargs)
        except Exception as exc:
            raise _provider_error(exc) from exc

        message = _first_choice_message(response)
        return ModelResponse(
            text=_message_text(message),
            model_id=request.model.id,
            provider_id=self.provider_id,
            reasoning_text=_reasoning_text(message),
            usage=_model_dump_mapping(_get_attr(response, "usage")),
            metadata=_response_metadata(response),
        )


def build_provider_registry(
    providers: tuple[ProviderSpec, ...],
    *,
    env: Mapping[str, str],
) -> ProviderRegistry:
    adapters: list[ProviderAdapter] = []
    for provider in providers:
        api_key = provider.resolve_api_key(env)
        if provider.api_style is ProviderApiStyle.OPENAI_RESPONSES:
            adapters.append(
                OpenAIResponsesAdapter(
                    provider=provider,
                    api_key=api_key,
                )
            )
            continue
        if provider.api_style is ProviderApiStyle.OPENAI_CHAT:
            adapters.append(
                OpenAIChatCompletionsAdapter(
                    provider=provider,
                    api_key=api_key,
                )
            )
            continue
        raise ProviderError(
            f"Unsupported provider API style: {provider.api_style}",
            kind=ProviderErrorKind.CONFIG,
        )
    return ProviderRegistry(adapters)


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


def _to_responses_input(request: ProviderRequest) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for message in request.messages.messages:
        role = _responses_role(message.role)
        items.append(
            {
                "role": role,
                "content": [_to_responses_part(part) for part in message.parts],
            }
        )
    return items


def _to_chat_messages(request: ProviderRequest) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for message in request.messages.messages:
        items.append(
            {
                "role": message.role.value,
                "content": _to_chat_content(message),
            }
        )
    return items


def _to_chat_content(message: Message) -> str | list[dict[str, object]]:
    if len(message.parts) == 1 and isinstance(message.parts[0], TextPart):
        return message.parts[0].text
    return [_to_chat_part(part) for part in message.parts]


def _to_responses_part(part: MessagePart) -> dict[str, object]:
    if isinstance(part, TextPart):
        return {"type": "input_text", "text": part.text}
    if isinstance(part, ImageUrlPart):
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


def _to_chat_part(part: MessagePart) -> dict[str, object]:
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text}
    if isinstance(part, ImageUrlPart):
        return {"type": "image_url", "image_url": {"url": part.url}}
    return {"type": "image_url", "image_url": {"url": _image_data_url(part)}}


def _responses_role(role: MessageRole) -> str:
    if role is MessageRole.TOOL:
        raise ProviderError(
            "OpenAI Responses input does not accept tool messages through this adapter",
            kind=ProviderErrorKind.CONFIG,
        )
    return role.value


def _image_data_url(part: ImagePart) -> str:
    encoded = base64.b64encode(part.data).decode("ascii")
    return f"data:{part.mime_type};base64,{encoded}"


def _apply_provider_options(
    kwargs: dict[str, object],
    options: Mapping[str, object] | None,
) -> None:
    if not options:
        return
    extra_body: dict[str, object] = {}
    for key, value in options.items():
        if key == "thinking":
            extra_body["thinking"] = value
            continue
        if key in {
            "prompt_cache_retention",
            "reasoning",
            "reasoning_effort",
            "service_tier",
            "store",
            "top_p",
            "verbosity",
        }:
            kwargs[key] = value
            continue
        raise ProviderError(
            f"Unsupported provider option: {key}",
            kind=ProviderErrorKind.CONFIG,
        )
    if extra_body:
        kwargs["extra_body"] = extra_body


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


def _responses_reasoning_text(response: object) -> str | None:
    output = _get_attr(response, "output")
    if not isinstance(output, list):
        return None
    texts: list[str] = []
    for item in output:
        item_type = _get_attr(item, "type")
        if item_type != "reasoning":
            continue
        summary = _get_attr(item, "summary")
        if isinstance(summary, list):
            for part in summary:
                text = _get_attr(part, "text")
                if isinstance(text, str):
                    texts.append(text)
    return "\n".join(texts) if texts else None


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


def _reasoning_text(message: object) -> str | None:
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
