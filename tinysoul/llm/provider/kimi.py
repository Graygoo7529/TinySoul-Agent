"""Kimi provider adapter."""

from __future__ import annotations

from collections.abc import Mapping
import re

from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
from tinysoul.llm.messages import AssistantMessage, Message
from tinysoul.llm.models import ModelCapability
from tinysoul.llm.reasoning import ReasoningKeep
from tinysoul.llm.tools import ToolUse

from .base import ProviderError, ProviderErrorKind, ProviderRequest
from .openai_sdk import (
    OpenAIAdapterBehavior,
    OpenAIChatCompletionsClient,
    OpenAICompatibleChatAdapter,
    provider_reasoning_keep,
)


class KimiProviderBehavior(OpenAIAdapterBehavior):
    """Kimi-specific option mapping."""

    def validate_tools(self, request: ProviderRequest) -> None:
        tools = request.tool_scope.visible_tools()
        if len(tools) > 128:
            raise ProviderError(
                "Kimi supports at most 128 tools",
                kind=ProviderErrorKind.CONFIG,
            )
        for tool in tools:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", tool.name):
                raise ProviderError(
                    f"Invalid Kimi tool name: {tool.name}",
                    kind=ProviderErrorKind.CONFIG,
                )
            parameters_type = tool.parameters.get("type")
            if parameters_type != "object":
                raise ProviderError(
                    "Kimi tool parameters root type must be object",
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
        return "auto"

    def include_chat_tool_result_name(self) -> bool:
        return True

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

    def chat_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> str | None:
        if provider_reasoning_keep(options, provider="Kimi") is not ReasoningKeep.CONTENT:
            return None
        if not isinstance(message, AssistantMessage) or message.reasoning is None:
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
                keep = provider_reasoning_keep(options, provider="Kimi")
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
            if key == "top_p":
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
