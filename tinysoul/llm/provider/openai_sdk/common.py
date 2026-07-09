"""Common OpenAI SDK adapter utilities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from openai import APIConnectionError, APIError, APIStatusError

from tinysoul.llm.models import (
    ModelCapability,
    ProviderOptions,
    ProviderRequestOverrides,
)
from tinysoul.llm.responses import AnswerFormat

from ..base import ProviderError, ProviderErrorKind, ProviderRequest
from .clients import ModelDumpable


def common_create_kwargs(request: ProviderRequest) -> dict[str, object]:
    overrides = request_overrides(request.provider_options)
    kwargs: dict[str, object] = {"model": request.model.provider_model}
    temperature = effective_temperature(request, overrides=overrides)
    if temperature is not None:
        kwargs["temperature"] = temperature
    max_output_tokens = effective_max_output_tokens(request, overrides=overrides)
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens
    return kwargs


def effective_temperature(
    request: ProviderRequest,
    *,
    overrides: ProviderRequestOverrides | None = None,
) -> float | None:
    resolved = overrides or request_overrides(request.provider_options)
    return (
        resolved.temperature
        if resolved.temperature is not None
        else request.temperature
    )


def effective_max_output_tokens(
    request: ProviderRequest,
    *,
    overrides: ProviderRequestOverrides | None = None,
) -> int | None:
    resolved = overrides or request_overrides(request.provider_options)
    return (
        resolved.max_output_tokens
        if resolved.max_output_tokens is not None
        else request.max_output_tokens
    )


def request_overrides(
    options: Mapping[str, object] | None,
) -> ProviderRequestOverrides:
    try:
        return ProviderOptions(options or {}).request_overrides()
    except (TypeError, ValueError) as exc:
        raise ProviderError(str(exc), kind=ProviderErrorKind.CONFIG) from exc


def provider_options(options: Mapping[str, object] | None) -> dict[str, object]:
    try:
        return ProviderOptions(options or {}).provider_values()
    except (TypeError, ValueError) as exc:
        raise ProviderError(str(exc), kind=ProviderErrorKind.CONFIG) from exc


def uses_native_json_output(request: ProviderRequest) -> bool:
    return request.answer_format is AnswerFormat.JSON_OBJECT and request.model.supports(
        ModelCapability.JSON_OBJECT_OUTPUT
    )


def provider_error(error: Exception) -> ProviderError:
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
    "effective_max_output_tokens",
    "effective_temperature",
    "get_attr",
    "model_dump_mapping",
    "provider_error",
    "provider_options",
    "request_overrides",
    "response_metadata",
    "uses_native_json_output",
]
