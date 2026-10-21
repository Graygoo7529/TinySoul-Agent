"""Shared adapter boundary checks, cache boundaries and stable error summaries."""

from collections.abc import Mapping

from tinysoul.infra.config import ConfigError
from tinysoul.llm.protocol.adapter_types import AdapterKind
from tinysoul.llm.protocol.cache import PromptCacheBreakpoint
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
            request.model.adapter_options.values,
            key="adapter_options",
            reasoning_effort=request.model.reasoning_effort,
        )
    except ConfigError as exc:
        raise ProviderError(
            "Invalid adapter options", kind=ProviderErrorKind.CONFIG
        ) from exc


def cache_boundaries(request: ProviderRequest) -> tuple[PromptCacheBreakpoint, ...]:
    """Resolve optional task prefix hints against the current message stack."""
    if (
        not request.model.supports(ModelCapability.PROMPT_CACHE)
        or not request.prompt_cache
    ):
        return ()
    options = request.model.adapter_options.values
    mode = options.get("prompt_cache_mode")
    if mode not in {"explicit", "implicit", "automatic"}:
        return ()
    selected = options.get("prompt_cache_boundaries")
    assert selected is None or isinstance(selected, (list, tuple))
    # Automatic modes only add markers when the model explicitly requests them.
    if selected is None and mode != "explicit":
        return ()
    result: dict[int, PromptCacheBreakpoint] = {}
    for point in request.prompt_cache.breakpoints:
        if point.message_index >= len(request.messages.messages):
            raise ProviderError(
                "Cache boundary is outside the message stack",
                kind=ProviderErrorKind.CONFIG,
            )
        if selected is None or point.name in selected:
            result.setdefault(point.message_index, point)
    return tuple(result[index] for index in sorted(result))


def cache_ttl(
    request: ProviderRequest, point: PromptCacheBreakpoint, default: str
) -> str:
    options = request.model.adapter_options.values
    overrides = options.get("prompt_cache_ttls", {})
    assert isinstance(overrides, Mapping)
    return str(overrides.get(point.name, options.get("prompt_cache_ttl", default)))


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
