"""DeepSeek provider adapter."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
from tinysoul.llm.messages import Message, MessageRole
from tinysoul.llm.reasoning import ReasoningKeep

from .base import ProviderError, ProviderErrorKind
from .openai_sdk import (
    OpenAIAdapterBehavior,
    OpenAIChatCompletionsClient,
    OpenAICompatibleChatAdapter,
    provider_reasoning_keep,
)


class DeepSeekProviderBehavior(OpenAIAdapterBehavior):
    """DeepSeek-specific option mapping."""

    def chat_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> str | None:
        if provider_reasoning_keep(options, provider="DeepSeek") is not ReasoningKeep.CONTENT:
            return None
        if message.role is not MessageRole.ASSISTANT or message.reasoning is None:
            return None
        return message.reasoning.content

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
    ) -> None:
        if not options:
            return
        extra_body: dict[str, object] = {}
        thinking_enabled = False

        for key, value in options.items():
            if key == "reasoning_keep":
                keep = provider_reasoning_keep(options, provider="DeepSeek")
                if keep is ReasoningKeep.ENCRYPTED:
                    raise ProviderError(
                        "DeepSeek does not support encrypted reasoning keep",
                        kind=ProviderErrorKind.CONFIG,
                    )
                continue
            if key == "thinking":
                thinking = _thinking_option(value)
                extra_body["thinking"] = thinking
                thinking_enabled = thinking.get("type") == "enabled"
                continue
            if key == "reasoning_effort":
                kwargs["reasoning_effort"] = _reasoning_effort(value)
                continue
            raise ProviderError(
                f"Unsupported DeepSeek provider option: {key}",
                kind=ProviderErrorKind.CONFIG,
            )

        if thinking_enabled:
            for ignored_key in (
                "temperature",
                "top_p",
                "presence_penalty",
                "frequency_penalty",
            ):
                kwargs.pop(ignored_key, None)
        if extra_body:
            kwargs["extra_body"] = extra_body


class DeepSeekProviderAdapter(OpenAICompatibleChatAdapter):
    """DeepSeek OpenAI-compatible Chat Completions adapter."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        completions: OpenAIChatCompletionsClient | None = None,
    ) -> None:
        if provider.api_style is not ProviderApiStyle.OPENAI_CHAT:
            raise ProviderError(
                "DeepSeek provider requires openai_chat API style",
                kind=ProviderErrorKind.CONFIG,
            )
        super().__init__(
            provider=provider,
            api_key=api_key,
            completions=completions,
            behavior=DeepSeekProviderBehavior(),
        )


def _thinking_option(value: object) -> dict[str, object]:
    if isinstance(value, str):
        if value not in {"enabled", "disabled"}:
            raise ProviderError(
                "DeepSeek thinking must be 'enabled' or 'disabled'",
                kind=ProviderErrorKind.CONFIG,
            )
        return {"type": value}
    if isinstance(value, Mapping):
        raw_type = value.get("type")
        if raw_type not in {"enabled", "disabled"}:
            raise ProviderError(
                "DeepSeek thinking.type must be 'enabled' or 'disabled'",
                kind=ProviderErrorKind.CONFIG,
            )
        return {str(key): item for key, item in value.items()}
    raise ProviderError(
        "DeepSeek thinking must be a string or table",
        kind=ProviderErrorKind.CONFIG,
    )


def _reasoning_effort(value: object) -> str:
    if value not in {"high", "max"}:
        raise ProviderError(
            "DeepSeek reasoning_effort must be 'high' or 'max'",
            kind=ProviderErrorKind.CONFIG,
        )
    return str(value)

