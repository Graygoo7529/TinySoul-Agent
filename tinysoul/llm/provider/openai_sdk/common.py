"""Common OpenAI SDK adapter utilities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from openai import APIConnectionError, APIError, APIStatusError

from tinysoul.llm.models import ModelCapability
from tinysoul.llm.responses import AnswerFormat

from ..base import ProviderError, ProviderErrorKind, ProviderFailureScope, ProviderRequest
from .clients import ModelDumpable


def common_create_kwargs(request: ProviderRequest) -> dict[str, object]:
    kwargs: dict[str, object] = {"model": request.binding.provider_model}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_output_tokens is not None:
        kwargs["max_output_tokens"] = request.max_output_tokens
    if request.timeout_seconds is not None:
        kwargs["timeout"] = request.timeout_seconds
    return kwargs


def uses_native_json_output(request: ProviderRequest) -> bool:
    return request.answer_format is AnswerFormat.JSON_OBJECT and request.model.supports(
        ModelCapability.JSON_OBJECT_OUTPUT
    )


def provider_error(error: Exception) -> ProviderError:
    if isinstance(error, ProviderError):
        return error
    if isinstance(error, APIStatusError):
        if error.status_code in {401, 403}:
            return ProviderError(str(error), kind=ProviderErrorKind.AUTH, scope=ProviderFailureScope.PROVIDER)
        if error.status_code in {408, 409, 429, 500, 502, 503, 504}:
            return ProviderError(str(error), kind=ProviderErrorKind.TRANSIENT, scope=ProviderFailureScope.PROVIDER)
        if error.status_code == 400:
            if _is_context_limit_error(error):
                return ProviderError(
                    str(error),
                    kind=ProviderErrorKind.CONTEXT_LIMIT,
                    scope=ProviderFailureScope.PROVIDER,
                )
            return ProviderError(str(error), kind=ProviderErrorKind.CONFIG, scope=ProviderFailureScope.PROVIDER)
        return ProviderError(str(error), kind=ProviderErrorKind.UNKNOWN, scope=ProviderFailureScope.PROVIDER)
    if isinstance(error, (APIConnectionError, APIError, TimeoutError)):
        return ProviderError(str(error), kind=ProviderErrorKind.TRANSIENT, scope=ProviderFailureScope.PROVIDER)
    return ProviderError(str(error), kind=ProviderErrorKind.UNKNOWN, scope=ProviderFailureScope.PROVIDER)


def _is_context_limit_error(error: APIStatusError) -> bool:
    values = [str(error)]
    body = getattr(error, "body", None)
    if isinstance(body, Mapping):
        pending: list[object] = [body]
        while pending:
            item = pending.pop()
            if isinstance(item, Mapping):
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, str):
                values.append(item)
    normalized = " ".join(values).lower()
    return any(
        marker in normalized
        for marker in (
            "context_length_exceeded",
            "context window",
            "context length",
            "context limit",
            "model token limit",
            "maximum context",
            "too many tokens",
        )
    )


def response_metadata(response: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in ("id", "model", "service_tier", "system_fingerprint", "status"):
        value = get_attr(response, key)
        if isinstance(value, str):
            result[key] = value
    return result


def model_dump_mapping(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    model_dump = get_attr(value, "model_dump")
    if callable(model_dump):
        dumped = cast(ModelDumpable, value).model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    return {}


def get_attr(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


__all__ = [
    "common_create_kwargs",
    "get_attr",
    "model_dump_mapping",
    "provider_error",
    "response_metadata",
    "uses_native_json_output",
]
