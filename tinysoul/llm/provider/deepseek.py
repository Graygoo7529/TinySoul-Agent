"""DeepSeek provider adapter."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.llm.config import ProviderSpec
from tinysoul.llm.adapter_types import AdapterKind, ProviderApiStyle
from tinysoul.llm.messages import AssistantMessage, Message
from tinysoul.llm.reasoning import ReasoningKeep
from tinysoul.llm.tools import ToolUse

from .base import ProviderError, ProviderErrorKind, ProviderFailureScope, ProviderRequest
from .openai_sdk import (
    OpenAIAdapterBehavior,
    OpenAIChatCompletionsClient,
    OpenAICompatibleChatAdapter,
    adapter_reasoning_keep,
)


class DeepSeekProviderBehavior(OpenAIAdapterBehavior):
    """DeepSeek-specific option mapping."""

    def validate_tools(self, request: ProviderRequest) -> None:
        tools = request.tool_scope.visible_tools()
        if len(tools) > 128:
            raise ProviderError(
                "DeepSeek supports at most 128 tools",
                kind=ProviderErrorKind.CONFIG,
            )
        for tool in tools:
            if tool.strict:
                raise ProviderError(
                    "DeepSeek adapter does not support strict tool calling",
                    kind=ProviderErrorKind.CONFIG,
                )
        if (
            request.tool_use is not ToolUse.DISABLED
            and tools
            and _deepseek_thinking_enabled(request.model.adapter_options.values)
            and adapter_reasoning_keep(
                request.model.adapter_options.values,
                adapter="DeepSeek",
            )
            is not ReasoningKeep.CONTENT
        ):
            raise ProviderError(
                "DeepSeek thinking with tools requires reasoning_keep='content'",
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
            return None
        return super().tool_choice_payload(request, api_style=api_style)

    def validate_chat_finish_reason(self, finish_reason: str | None) -> None:
        if finish_reason == "insufficient_system_resource":
            raise ProviderError(
                "DeepSeek generation was interrupted by insufficient inference resources",
                kind=ProviderErrorKind.TRANSIENT,
                scope=ProviderFailureScope.PROVIDER,
            )

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
        thinking_enabled = _deepseek_thinking_enabled(options)
        if thinking_enabled:
            for ignored_key in (
                "temperature",
                "top_p",
                "presence_penalty",
                "frequency_penalty",
            ):
                kwargs.pop(ignored_key, None)
        if not options:
            return
        extra_body: dict[str, object] = {}

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
                continue
            if key == "reasoning_effort":
                kwargs["reasoning_effort"] = _reasoning_effort(value)
                continue
            raise ProviderError(
                f"Unsupported DeepSeek adapter option: {key}",
                kind=ProviderErrorKind.CONFIG,
            )

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
        if AdapterKind.DEEPSEEK not in provider.adapters:
            raise ProviderError(
                "DeepSeek provider does not declare the deepseek adapter",
                kind=ProviderErrorKind.CONFIG,
                scope=ProviderFailureScope.MODEL,
            )
        super().__init__(
            provider=provider,
            adapter_kind=AdapterKind.DEEPSEEK,
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
    if value not in {"low", "high", "max"}:
        raise ProviderError(
            "DeepSeek reasoning_effort must be 'low', 'high', or 'max'",
            kind=ProviderErrorKind.CONFIG,
        )
    return str(value)


def _rename_max_tokens(kwargs: dict[str, object]) -> None:
    value = kwargs.pop("max_completion_tokens", None)
    if value is not None:
        kwargs["max_tokens"] = value


def _deepseek_thinking_enabled(options: Mapping[str, object] | None) -> bool:
    if not options or "thinking" not in options:
        return True
    value = options.get("thinking")
    return _thinking_option(value).get("type") == "enabled"
