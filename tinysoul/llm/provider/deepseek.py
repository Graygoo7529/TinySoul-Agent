"""DeepSeek provider adapter."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
from tinysoul.llm.messages import AssistantMessage, Message
from tinysoul.llm.reasoning import ReasoningKeep
from tinysoul.llm.tools import ToolUse

from .base import ProviderError, ProviderErrorKind, ProviderRequest
from .openai_sdk import (
    OpenAIAdapterBehavior,
    OpenAIChatCompletionsClient,
    OpenAICompatibleChatAdapter,
    adapter_reasoning_keep,
)


class DeepSeekProviderBehavior(OpenAIAdapterBehavior):
    """DeepSeek-specific option mapping."""

    def validate_tools(self, request: ProviderRequest) -> None:
        for tool in request.tool_scope.visible_tools():
            if tool.strict:
                raise ProviderError(
                    "DeepSeek adapter does not support strict tool calling",
                    kind=ProviderErrorKind.CONFIG,
                )

    def tool_choice_payload(
        self,
        request: ProviderRequest,
        *,
        api_style: ProviderApiStyle,
    ) -> object | None:
        if request.tool_use is ToolUse.DISABLED:
            return None
        if _deepseek_thinking_enabled(request.model.adapter_options.values):
            return "auto"
        return None

    def chat_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> str | None:
        if adapter_reasoning_keep(options, adapter="DeepSeek") is not ReasoningKeep.CONTENT:
            return None
        if not isinstance(message, AssistantMessage) or message.reasoning is None:
            return None
        return message.reasoning.content

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
        *,
        request: ProviderRequest,
    ) -> None:
        _rename_max_tokens(kwargs)
        if not options:
            return
        extra_body: dict[str, object] = {}
        thinking_enabled = False

        for key, value in options.items():
            if key == "reasoning_keep":
                keep = adapter_reasoning_keep(options, adapter="DeepSeek")
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
                f"Unsupported DeepSeek adapter option: {key}",
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


def _rename_max_tokens(kwargs: dict[str, object]) -> None:
    value = kwargs.pop("max_completion_tokens", None)
    if value is not None:
        kwargs["max_tokens"] = value


def _deepseek_thinking_enabled(options: Mapping[str, object] | None) -> bool:
    if not options:
        return False
    value = options.get("thinking")
    if value == "enabled":
        return True
    if isinstance(value, Mapping):
        return value.get("type") == "enabled"
    return False
