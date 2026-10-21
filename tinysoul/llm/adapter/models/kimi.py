"""Kimi provider adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from tinysoul.llm.config.loader import ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.reasoning import NativeReplayMode
from tinysoul.llm.protocol.tools import ToolUse

from ..base import (
    ProviderError,
    ProviderErrorKind,
    ProviderRequest,
)
from ..openai.chat import OpenAIChatAdapter
from ..openai.clients import OpenAIChatCompletionsClient
from ..openai.options import ChatOptions


class KimiOptions(ChatOptions, total=False):
    variant: str
    thinking: str


class KimiAdapter(OpenAIChatAdapter):
    """Kimi-specific option mapping."""

    def validate_request(self, request: ProviderRequest) -> None:
        tools = request.tool_scope.visible_tools()
        if len(tools) > 128:
            raise ProviderError(
                "Kimi supports at most 128 tools",
                kind=ProviderErrorKind.CONFIG,
            )
        for tool in tools:
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
        api_mode: ApiMode,
    ) -> object | None:
        if request.tool_use is ToolUse.DISABLED:
            return None
        if _uses_k3_variant(request) and request.tool_use is ToolUse.REQUIRED:
            return "required"
        return "auto"

    def include_chat_tool_result_name(self) -> bool:
        return True

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
        *,
        request: ProviderRequest,
    ) -> None:
        super().apply_options(kwargs, options, request=request)
        values = cast(KimiOptions, options or {})
        extra_body: dict[str, object] = dict(values.get("extra_body", {}))
        thinking: dict[str, object] = {}
        if "thinking" in values:
            thinking["type"] = values["thinking"]
        if values.get("variant") == "k2" and values.get("native_replay") == "content":
            thinking["keep"] = "all"
        if thinking:
            extra_body["thinking"] = thinking
        if extra_body:
            kwargs["extra_body"] = extra_body

    def normalize_sampling(
        self, kwargs: dict[str, object], request: ProviderRequest
    ) -> None:
        """K2.x and K3 fix sampling parameters in the provider API."""

        kwargs.pop("temperature", None)
        kwargs.pop("top_p", None)

    def replay_mode(self, request: ProviderRequest) -> NativeReplayMode:
        # K3 preserves reasoning_content across continuations by contract.
        if _uses_k3_variant(request):
            return NativeReplayMode.CONTENT
        return super().replay_mode(request)

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        completions: OpenAIChatCompletionsClient,
    ) -> None:
        super().__init__(
            provider=provider,
            adapter_kind=AdapterKind.KIMI,
            completions=completions,
        )


def _uses_k3_variant(request: ProviderRequest) -> bool:
    return request.model.adapter_options.values.get("variant") == "k3"
