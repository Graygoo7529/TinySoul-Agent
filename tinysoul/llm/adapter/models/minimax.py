"""MiniMax provider adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from tinysoul.llm.config.loader import ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.reasoning import Reasoning

from ..base import (
    ProviderError,
    ProviderErrorKind,
    ProviderRequest,
)
from ..openai.chat import OpenAIChatAdapter
from ..openai.clients import OpenAIChatCompletionsClient
from ..openai.options import ChatOptions


class MiniMaxOptions(ChatOptions, total=False):
    thinking: str
    reasoning_split: bool


class MiniMaxAdapter(OpenAIChatAdapter):
    """MiniMax-specific option mapping."""

    supports_prompt_cache_key = False

    def tool_choice_payload(
        self,
        request: ProviderRequest,
        *,
        api_mode: ApiMode,
    ) -> object | None:
        return None

    def validate_request(self, request: ProviderRequest) -> None:
        for tool in request.tool_scope.visible_tools():
            if tool.parameters.get("type") != "object":
                raise ProviderError(
                    "MiniMax tool parameters root type must be object",
                    kind=ProviderErrorKind.CONFIG,
                )
            if tool.strict is not None:
                raise ProviderError(
                    "MiniMax does not support strict tool calling",
                    kind=ProviderErrorKind.CONFIG,
                )

    def chat_output_reasoning(self, message: object) -> Reasoning | None:
        content = _reasoning_text(message)
        if content is None:
            return None
        return Reasoning(content=content, summary=content)

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
        *,
        request: ProviderRequest,
    ) -> None:
        super().apply_options(kwargs, options, request=request)
        values = cast(MiniMaxOptions, options or {})
        extra_body: dict[str, object] = dict(values.get("extra_body", {}))
        if "thinking" in values:
            extra_body["thinking"] = {"type": values["thinking"]}
        if "reasoning_split" in values:
            extra_body["reasoning_split"] = values["reasoning_split"]
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
            adapter_kind=AdapterKind.MINIMAX,
            completions=completions,
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


def _get_attr(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)
