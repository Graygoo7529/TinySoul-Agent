"""DeepSeek provider adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from tinysoul.llm.config.loader import ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.messages import (
    ImagePart,
    ImageUrlPart,
    UserMessage,
)
from tinysoul.llm.protocol.reasoning import ReasoningKeep
from tinysoul.llm.protocol.tools import ToolSpec, ToolUse

from ..base import (
    ProviderError,
    ProviderErrorKind,
    ProviderFailureScope,
    ProviderRequest,
)
from ..openai.base import adapter_reasoning_keep
from ..openai.chat import OpenAIChatAdapter
from ..openai.clients import OpenAIChatCompletionsClient
from ..openai.options import ChatOptions


class DeepSeekOptions(ChatOptions, total=False):
    thinking: str


class DeepSeekAdapter(OpenAIChatAdapter):
    """DeepSeek-specific option mapping."""

    output_token_field = "max_tokens"

    supports_prompt_cache_key = False

    def validate_request(self, request: ProviderRequest) -> None:
        _validate_image_messages(request)
        tools = request.tool_scope.visible_tools()
        _validate_deepseek_tools(tools)
        _validate_thinking_tool_replay(request, has_tools=bool(tools))

    def tool_choice_payload(
        self,
        request: ProviderRequest,
        *,
        api_mode: ApiMode,
    ) -> object | None:
        if request.tool_use is ToolUse.DISABLED:
            return None
        if _deepseek_thinking_enabled(request.model.adapter_options.values):
            return None
        return super().tool_choice_payload(request, api_mode=api_mode)

    def validate_chat_finish_reason(self, finish_reason: str | None) -> None:
        if finish_reason == "insufficient_system_resource":
            raise ProviderError(
                "DeepSeek generation was interrupted by insufficient inference resources",
                kind=ProviderErrorKind.TRANSIENT,
                scope=ProviderFailureScope.PROVIDER,
            )

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
        *,
        request: ProviderRequest,
    ) -> None:
        super().apply_options(kwargs, options, request=request)
        values = cast(DeepSeekOptions, options or {})
        if _deepseek_thinking_enabled(options):
            kwargs.pop("temperature", None)
        extra_body: dict[str, object] = dict(values.get("extra_body", {}))
        if "thinking" in values:
            extra_body["thinking"] = {"type": values["thinking"]}
        if extra_body:
            kwargs["extra_body"] = extra_body

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        completions: OpenAIChatCompletionsClient,
    ) -> None:
        super().__init__(
            provider=provider,
            adapter_kind=AdapterKind.DEEPSEEK,
            completions=completions,
        )


def _deepseek_thinking_enabled(options: Mapping[str, object] | None) -> bool:
    return (options or {}).get("thinking", "enabled") == "enabled"


def _validate_image_messages(request: ProviderRequest) -> None:
    for message in request.messages.messages:
        if isinstance(message, UserMessage):
            continue
        if any(isinstance(part, (ImagePart, ImageUrlPart)) for part in message.parts):
            raise ProviderError(
                "DeepSeek image input is only supported in user messages",
                kind=ProviderErrorKind.CAPABILITY,
            )


def _validate_deepseek_tools(tools: tuple[ToolSpec, ...]) -> None:
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


def _validate_thinking_tool_replay(
    request: ProviderRequest,
    *,
    has_tools: bool,
) -> None:
    if (
        request.tool_use is not ToolUse.DISABLED
        and has_tools
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
