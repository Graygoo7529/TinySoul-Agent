"""Provider behavior hooks for OpenAI SDK shaped adapters."""

from __future__ import annotations

from collections.abc import Mapping

from tinysoul.infra.json import JsonObject
from tinysoul.llm.config import ProviderApiStyle
from tinysoul.llm.messages import Message
from tinysoul.llm.reasoning import Reasoning, ReasoningKeep
from tinysoul.llm.tools import ToolSpec

from ..base import ProviderError, ProviderErrorKind, ProviderRequest
from .payloads import to_chat_tool, to_responses_tool
from .response_parsing import (
    chat_reasoning_content,
    responses_encrypted_reasoning_items,
    responses_reasoning_summary,
)


class OpenAIAdapterBehavior:
    """Supplier-specific behavior for OpenAI SDK shaped APIs."""

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
    ) -> None:
        if not options:
            return
        key = next(iter(options))
        raise ProviderError(
            f"Unsupported provider option: {key}",
            kind=ProviderErrorKind.CONFIG,
        )

    def validate_tools(self, request: ProviderRequest) -> None:
        return

    def validate_tool_choice(self, request: ProviderRequest) -> None:
        return

    def tool_payload(
        self,
        tool: ToolSpec,
        *,
        api_style: ProviderApiStyle,
    ) -> dict[str, object]:
        if api_style is ProviderApiStyle.OPENAI_RESPONSES:
            return to_responses_tool(tool)
        return to_chat_tool(tool)

    def tool_choice_payload(
        self,
        request: ProviderRequest,
        *,
        api_style: ProviderApiStyle,
    ) -> object | None:
        return None

    def include_chat_tool_result_name(self) -> bool:
        return False

    def apply_prompt_cache(
        self,
        kwargs: dict[str, object],
        request: ProviderRequest,
    ) -> None:
        return

    def chat_output_reasoning(self, message: object) -> Reasoning | None:
        content = chat_reasoning_content(message)
        if content is None:
            return None
        return Reasoning(content=content, summary=content)

    def responses_output_reasoning(self, response: object) -> Reasoning | None:
        summary = responses_reasoning_summary(response)
        encrypted_items = responses_encrypted_reasoning_items(response)
        if summary is None and not encrypted_items:
            return None
        return Reasoning(summary=summary, encrypted_items=encrypted_items)

    def chat_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> str | None:
        return None

    def responses_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
    ) -> tuple[JsonObject, ...]:
        return ()


def provider_reasoning_keep(
    options: Mapping[str, object] | None,
    *,
    provider: str,
) -> ReasoningKeep:
    if options is None:
        return ReasoningKeep.NONE
    value = options.get("reasoning_keep")
    if value is None:
        return ReasoningKeep.NONE
    if not isinstance(value, str):
        raise ProviderError(
            f"{provider} reasoning_keep must be a string",
            kind=ProviderErrorKind.CONFIG,
        )
    try:
        return ReasoningKeep(value)
    except ValueError as exc:
        raise ProviderError(
            f"{provider} reasoning_keep must be 'none', 'content', or 'encrypted'",
            kind=ProviderErrorKind.CONFIG,
        ) from exc


__all__ = [
    "OpenAIAdapterBehavior",
    "provider_reasoning_keep",
]
