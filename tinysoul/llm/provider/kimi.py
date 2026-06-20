"""Kimi provider adapter."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
from tinysoul.llm.messages import Message, MessageRole

from .base import ProviderError, ProviderErrorKind
from .openai_sdk import (
    OpenAIAdapterBehavior,
    OpenAIChatCompletionsClient,
    OpenAICompatibleChatAdapter,
)


class KimiProviderBehavior(OpenAIAdapterBehavior):
    """Kimi-specific option mapping."""

    def include_chat_message_reasoning(self, message: Message) -> bool:
        return message.role is MessageRole.ASSISTANT

    def apply_options(
        self,
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
            if key in {"partial", "top_p"}:
                kwargs[key] = value
                continue
            raise ProviderError(
                f"Unsupported Kimi provider option: {key}",
                kind=ProviderErrorKind.CONFIG,
            )
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
