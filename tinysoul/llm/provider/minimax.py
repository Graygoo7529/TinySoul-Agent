"""MiniMax provider adapter."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
from tinysoul.llm.messages import Message, MessageRole
from tinysoul.llm.reasoning import Reasoning, ReasoningKeep

from .base import ProviderError, ProviderErrorKind
from .openai_sdk import (
    OpenAIAdapterBehavior,
    OpenAIChatCompletionsClient,
    OpenAICompatibleChatAdapter,
    provider_reasoning_keep,
)


class MiniMaxProviderBehavior(OpenAIAdapterBehavior):
    """MiniMax-specific option mapping."""

    def chat_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> str | None:
        if provider_reasoning_keep(options, provider="MiniMax") is not ReasoningKeep.CONTENT:
            return None
        if message.role is not MessageRole.ASSISTANT or message.reasoning is None:
            return None
        return message.reasoning.content

    def chat_output_reasoning(self, message: object) -> Reasoning | None:
        content = _reasoning_text(message)
        if content is None:
            return None
        return Reasoning(content=content, summary=content)

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
                extra_body["thinking"] = _thinking_option(value)
                continue
            if key == "reasoning_split":
                extra_body["reasoning_split"] = _bool_option(
                    value,
                    key="reasoning_split",
                )
                continue
            if key == "reasoning_keep":
                keep = provider_reasoning_keep(options, provider="MiniMax")
                if keep is ReasoningKeep.ENCRYPTED:
                    raise ProviderError(
                        "MiniMax does not support encrypted reasoning keep",
                        kind=ProviderErrorKind.CONFIG,
                    )
                continue
            if key == "top_p":
                kwargs[key] = _number_option(value, key=key)
                continue
            raise ProviderError(
                f"Unsupported MiniMax provider option: {key}",
                kind=ProviderErrorKind.CONFIG,
            )
        if extra_body:
            kwargs["extra_body"] = extra_body


class MiniMaxProviderAdapter(OpenAICompatibleChatAdapter):
    """MiniMax OpenAI-compatible Chat Completions adapter."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        completions: OpenAIChatCompletionsClient | None = None,
    ) -> None:
        if provider.api_style is not ProviderApiStyle.OPENAI_CHAT:
            raise ProviderError(
                "MiniMax provider requires openai_chat API style",
                kind=ProviderErrorKind.CONFIG,
            )
        super().__init__(
            provider=provider,
            api_key=api_key,
            completions=completions,
            behavior=MiniMaxProviderBehavior(),
        )


def _thinking_option(value: object) -> dict[str, object]:
    if isinstance(value, str):
        if value not in {"enabled", "disabled", "adaptive"}:
            raise ProviderError(
                "MiniMax thinking must be 'enabled', 'disabled', or 'adaptive'",
                kind=ProviderErrorKind.CONFIG,
            )
        return {"type": value}
    if isinstance(value, Mapping):
        raw_type = value.get("type")
        if raw_type not in {"enabled", "disabled", "adaptive"}:
            raise ProviderError(
                "MiniMax thinking.type must be 'enabled', 'disabled', or 'adaptive'",
                kind=ProviderErrorKind.CONFIG,
            )
        return {str(key): item for key, item in value.items()}
    raise ProviderError(
        "MiniMax thinking must be a string or table",
        kind=ProviderErrorKind.CONFIG,
    )


def _reasoning_text(message: object) -> str | None:
    content = _get_attr(message, "reasoning_content")
    if isinstance(content, str) and content:
        return content

    details = _get_attr(message, "reasoning_details")
    if not isinstance(details, list):
        return None
    texts: list[str] = []
    for detail in details:
        text = _get_attr(detail, "text")
        if isinstance(text, str) and text:
            texts.append(text)
    return "\n".join(texts) if texts else None


def _bool_option(value: object, *, key: str) -> bool:
    if not isinstance(value, bool):
        raise ProviderError(
            f"MiniMax {key} must be a boolean",
            kind=ProviderErrorKind.CONFIG,
        )
    return value


def _number_option(value: object, *, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError(
            f"MiniMax {key} must be a number",
            kind=ProviderErrorKind.CONFIG,
        )
    return float(value)


def _get_attr(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)
