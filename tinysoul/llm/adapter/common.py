"""Shared adapter boundary checks, cache boundaries and stable error summaries."""

from tinysoul.infra.config import ConfigError
from tinysoul.llm.protocol.adapter_types import AdapterKind
from tinysoul.llm.protocol.models import ModelCapability

from .base import (
    ProviderError,
    ProviderErrorKind,
    ProviderFailureScope,
    ProviderRequest,
)
from .catalog import adapter_spec


def validate_request(
    request: ProviderRequest, provider_id: str, kind: AdapterKind
) -> None:
    if request.binding.provider_id != provider_id or request.model.adapter is not kind:
        raise ProviderError(
            "Model binding does not match adapter", kind=ProviderErrorKind.CONFIG
        )
    try:
        adapter_spec(kind).validate_options(
            request.model.adapter_options.values, key="adapter_options"
        )
    except ConfigError as exc:
        raise ProviderError(
            "Invalid adapter options", kind=ProviderErrorKind.CONFIG
        ) from exc


def cache_boundary(request: ProviderRequest) -> int | None:
    if not request.model.supports(ModelCapability.PROMPT_CACHE):
        return None
    cache = request.prompt_cache
    index = cache.breakpoint_message_index if cache else None
    explicit = (
        request.model.adapter_options.values.get("prompt_cache_mode") == "explicit"
    )
    if explicit and index is None:
        raise ProviderError(
            "Explicit caching requires a task prefix boundary",
            kind=ProviderErrorKind.CONFIG,
        )
    if index is not None and index >= len(request.messages.messages):
        raise ProviderError(
            "Cache boundary is outside the message stack", kind=ProviderErrorKind.CONFIG
        )
    return index


def status_error(status: int | None, detail: str = "") -> ProviderError:
    if status in {401, 403}:
        kind = ProviderErrorKind.AUTH
    elif status in {408, 409, 429} or status is not None and status >= 500:
        kind = ProviderErrorKind.TRANSIENT
    elif status in {400, 413, 422}:
        kind = (
            ProviderErrorKind.CONTEXT_LIMIT
            if any(
                word in detail.lower()
                for word in (
                    "context_length_exceeded",
                    "context window",
                    "context length",
                    "too many tokens",
                    "input token count exceeds",
                )
            )
            else ProviderErrorKind.CONFIG
        )
    else:
        kind = ProviderErrorKind.UNKNOWN
    return ProviderError(
        f"Provider request failed ({kind.value}, HTTP {status})",
        kind=kind,
        scope=ProviderFailureScope.PROVIDER,
    )
