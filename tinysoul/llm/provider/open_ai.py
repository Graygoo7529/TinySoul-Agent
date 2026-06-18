"""OpenAI provider adapter."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.llm.config import ProviderApiStyle, ProviderSpec

from .base import ProviderError, ProviderErrorKind
from .openai_sdk import (
    OpenAIAdapterBehavior,
    OpenAIResponsesAdapter,
    OpenAIResponsesClient,
)


class OpenAIProviderBehavior(OpenAIAdapterBehavior):
    """OpenAI Responses option mapping."""

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
    ) -> None:
        if not options:
            return
        for key, value in options.items():
            if key == "reasoning_effort":
                kwargs["reasoning"] = {"effort": _string_option(value, key=key)}
                continue
            if key == "verbosity":
                _merge_text_option(kwargs, "verbosity", _string_option(value, key=key))
                continue
            if key in {"prompt_cache_retention", "service_tier"}:
                kwargs[key] = _string_option(value, key=key)
                continue
            if key in {"store"}:
                kwargs[key] = _bool_option(value, key=key)
                continue
            if key in {"top_p"}:
                kwargs[key] = _number_option(value, key=key)
                continue
            raise ProviderError(
                f"Unsupported OpenAI provider option: {key}",
                kind=ProviderErrorKind.CONFIG,
            )


class OpenAIProviderAdapter(OpenAIResponsesAdapter):
    """OpenAI official provider adapter."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        responses: OpenAIResponsesClient | None = None,
    ) -> None:
        if provider.api_style is not ProviderApiStyle.OPENAI_RESPONSES:
            raise ProviderError(
                "OpenAI provider requires openai_responses API style",
                kind=ProviderErrorKind.CONFIG,
            )
        super().__init__(
            provider=provider,
            api_key=api_key,
            responses=responses,
            behavior=OpenAIProviderBehavior(),
        )


def _merge_text_option(kwargs: dict[str, object], key: str, value: object) -> None:
    text = kwargs.get("text")
    if text is None:
        kwargs["text"] = {key: value}
        return
    if not isinstance(text, Mapping):
        raise ProviderError(
            "OpenAI text option cannot be merged",
            kind=ProviderErrorKind.CONFIG,
        )
    merged = {str(item_key): item for item_key, item in text.items()}
    merged[key] = value
    kwargs["text"] = merged


def _string_option(value: object, *, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderError(
            f"OpenAI {key} must be a non-empty string",
            kind=ProviderErrorKind.CONFIG,
        )
    return value


def _bool_option(value: object, *, key: str) -> bool:
    if not isinstance(value, bool):
        raise ProviderError(
            f"OpenAI {key} must be a boolean",
            kind=ProviderErrorKind.CONFIG,
        )
    return value


def _number_option(value: object, *, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError(
            f"OpenAI {key} must be a number",
            kind=ProviderErrorKind.CONFIG,
        )
    return float(value)
