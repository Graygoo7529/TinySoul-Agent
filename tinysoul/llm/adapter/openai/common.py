"""Common OpenAI SDK adapter utilities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from openai import APIStatusError

from tinysoul.llm.protocol.models import ModelCapability
from tinysoul.llm.protocol.responses import AnswerFormat
from tinysoul.llm.protocol.usage import TokenUsage

from ..base import (
    ProviderError,
    ProviderErrorKind,
    ProviderFailureScope,
    ProviderRequest,
)
from ..common import status_error
from .clients import ModelDumpable


def openai_usage(value: object) -> TokenUsage:
    def number(obj: object, key: str) -> int | None:
        item = get_attr(obj, key)
        return item if type(item) is int else None

    chat = get_attr(value, "prompt_tokens") is not None
    input_detail = get_attr(
        value, "prompt_tokens_details" if chat else "input_tokens_details"
    )
    output_detail = get_attr(
        value, "completion_tokens_details" if chat else "output_tokens_details"
    )
    cached = number(input_detail, "cached_tokens")
    if cached is None:
        cached = number(value, "prompt_cache_hit_tokens")
    return TokenUsage(
        input_tokens=number(value, "prompt_tokens" if chat else "input_tokens"),
        output_tokens=number(value, "completion_tokens" if chat else "output_tokens"),
        cached_input_tokens=cached,
        cache_creation_input_tokens=number(input_detail, "cache_write_tokens"),
        reasoning_tokens=number(output_detail, "reasoning_tokens"),
    )


def common_create_kwargs(request: ProviderRequest) -> dict[str, object]:
    kwargs: dict[str, object] = {"model": request.binding.provider_model}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    if request.max_output_tokens is not None:
        kwargs["max_output_tokens"] = request.max_output_tokens
    if request.timeout_seconds is not None:
        kwargs["timeout"] = request.timeout_seconds
    extra_body = request.model.adapter_options.extra_body()
    if extra_body:
        kwargs["extra_body"] = dict(extra_body)
    return kwargs


def uses_native_json_output(request: ProviderRequest) -> bool:
    return request.answer_format is AnswerFormat.JSON_OBJECT and request.model.supports(
        ModelCapability.JSON_OBJECT_OUTPUT
    )


def provider_error(error: Exception) -> ProviderError:
    if isinstance(error, ProviderError):
        return error
    if isinstance(error, APIStatusError):
        return status_error(error.status_code, str(error))
    return ProviderError(
        "Provider transport request failed",
        kind=ProviderErrorKind.TRANSIENT,
        scope=ProviderFailureScope.PROVIDER,
    )


def response_metadata(response: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in ("id", "model", "service_tier", "system_fingerprint", "status"):
        value = get_attr(response, key)
        if isinstance(value, str):
            result[key] = value
    return result


def model_dump_mapping(
    value: object, *, exclude_none: bool = False
) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {
            str(key): item
            for key, item in value.items()
            if not exclude_none or item is not None
        }
    model_dump = get_attr(value, "model_dump")
    if callable(model_dump):
        dumped = cast(ModelDumpable, value).model_dump(
            mode="json", exclude_none=exclude_none
        )
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
