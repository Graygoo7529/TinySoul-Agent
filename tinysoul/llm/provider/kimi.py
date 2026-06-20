"""Kimi provider adapter."""

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
)


class KimiProviderBehavior(OpenAIAdapterBehavior):
    """Kimi-specific option mapping."""

    def chat_message_reasoning_content(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> str | None:
        if _reasoning_keep(options) is not ReasoningKeep.CONTENT:
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
        thinking: dict[str, object] = {}
        for key, value in options.items():
            if key == "thinking":
                thinking["type"] = _thinking_type(value)
                continue
            if key == "reasoning_keep":
                keep = _reasoning_keep(options)
                if keep is ReasoningKeep.CONTENT:
                    thinking["keep"] = "all"
                    continue
                if keep is ReasoningKeep.NONE:
                    continue
                raise ProviderError(
                    "Kimi does not support encrypted reasoning keep",
                    kind=ProviderErrorKind.CONFIG,
                )
                continue
            if key in {"partial", "top_p"}:
                kwargs[key] = value
                continue
            raise ProviderError(
                f"Unsupported Kimi provider option: {key}",
                kind=ProviderErrorKind.CONFIG,
            )
        if thinking:
            extra_body["thinking"] = thinking
        if extra_body:
            kwargs["extra_body"] = extra_body


class KimiProviderAdapter(OpenAICompatibleChatAdapter):
    """Kimi OpenAI-compatible Chat Completions adapter."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        completions: OpenAIChatCompletionsClient | None = None,
    ) -> None:
        if provider.api_style is not ProviderApiStyle.OPENAI_CHAT:
            raise ProviderError(
                "Kimi provider requires openai_chat API style",
                kind=ProviderErrorKind.CONFIG,
            )
        super().__init__(
            provider=provider,
            api_key=api_key,
            completions=completions,
            behavior=KimiProviderBehavior(),
        )


def _thinking_type(value: object) -> str:
    if value not in {"enabled", "disabled"}:
        raise ProviderError(
            "Kimi thinking must be 'enabled' or 'disabled'",
            kind=ProviderErrorKind.CONFIG,
        )
    return str(value)


def _reasoning_keep(options: Mapping[str, object] | None) -> ReasoningKeep:
    if options is None:
        return ReasoningKeep.NONE
    value = options.get("reasoning_keep")
    if value is None:
        return ReasoningKeep.NONE
    if isinstance(value, str):
        return ReasoningKeep(value)
    raise ProviderError(
        "Kimi reasoning_keep must be a string",
        kind=ProviderErrorKind.CONFIG,
    )
