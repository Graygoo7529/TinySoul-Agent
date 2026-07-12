"""OpenAI provider adapter."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.infra.json import JsonObject
from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
from tinysoul.llm.messages import AssistantMessage, Message
from tinysoul.llm.models import ModelCapability
from tinysoul.llm.reasoning import ReasoningKeep

from .base import ProviderError, ProviderErrorKind, ProviderRequest
from .openai_sdk import (
    OpenAIAdapterBehavior,
    OpenAIResponsesAdapter,
    OpenAIResponsesClient,
    provider_reasoning_keep,
)


class OpenAIProviderBehavior(OpenAIAdapterBehavior):
    """OpenAI Responses option mapping."""

    def apply_prompt_cache(
        self,
        kwargs: dict[str, object],
        request: ProviderRequest,
    ) -> None:
        if request.prompt_cache is None:
            return
        if not request.model.supports(ModelCapability.PROMPT_CACHE):
            return
        kwargs["prompt_cache_key"] = request.prompt_cache.key

    def responses_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> tuple[JsonObject, ...]:
        if not isinstance(message, AssistantMessage) or message.reasoning is None:
            return ()
        reasoning = message.reasoning
        keep = provider_reasoning_keep(options, provider="OpenAI")
        if keep is ReasoningKeep.NONE:
            return ()
        if keep is ReasoningKeep.ENCRYPTED:
            return reasoning.encrypted_items
        if reasoning.content is not None:
            raise ProviderError(
                "OpenAI does not support text reasoning content input",
                kind=ProviderErrorKind.CONFIG,
            )
        raise ProviderError(
            "OpenAI does not support text reasoning keep",
            kind=ProviderErrorKind.CONFIG,
        )

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
    ) -> None:
        if not options:
            return
        for key, value in options.items():
            if key == "reasoning_effort":
                _merge_reasoning_option(
                    kwargs,
                    "effort",
                    _string_option(value, key=key),
                )
                continue
            if key == "reasoning_summary":
                _merge_reasoning_option(
                    kwargs,
                    "summary",
                    _reasoning_summary_option(value),
                )
                continue
            if key == "reasoning_keep":
                keep = provider_reasoning_keep(options, provider="OpenAI")
                if keep is ReasoningKeep.ENCRYPTED:
                    _merge_include(kwargs, "reasoning.encrypted_content")
                    continue
                if keep is ReasoningKeep.NONE:
                    continue
                raise ProviderError(
                    "OpenAI does not support text reasoning keep",
                    kind=ProviderErrorKind.CONFIG,
                )
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
    """OpenAI Responses behavior for official or compatible proxy endpoints."""

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


def _merge_reasoning_option(
    kwargs: dict[str, object],
    key: str,
    value: object,
) -> None:
    reasoning = kwargs.get("reasoning")
    if reasoning is None:
        kwargs["reasoning"] = {key: value}
        return
    if not isinstance(reasoning, Mapping):
        raise ProviderError(
            "OpenAI reasoning option cannot be merged",
            kind=ProviderErrorKind.CONFIG,
        )
    merged = {str(item_key): item for item_key, item in reasoning.items()}
    merged[key] = value
    kwargs["reasoning"] = merged


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


def _merge_include(kwargs: dict[str, object], value: str) -> None:
    include = kwargs.get("include")
    if include is None:
        kwargs["include"] = [value]
        return
    if not isinstance(include, list) or not all(
        isinstance(item, str) for item in include
    ):
        raise ProviderError(
            "OpenAI include option cannot be merged",
            kind=ProviderErrorKind.CONFIG,
        )
    if value not in include:
        kwargs["include"] = [*include, value]


def _reasoning_summary_option(value: object) -> str:
    if value not in {"auto", "concise", "detailed"}:
        raise ProviderError(
            "OpenAI reasoning_summary must be 'auto', 'concise', or 'detailed'",
            kind=ProviderErrorKind.CONFIG,
        )
    return str(value)


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
