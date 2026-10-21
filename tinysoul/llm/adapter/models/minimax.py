"""MiniMax provider adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from tinysoul.llm.config.loader import ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode

from ..base import (
    ProviderError,
    ProviderErrorKind,
    ProviderRequest,
)
from ..openai.chat import OpenAIChatAdapter
from ..openai.clients import OpenAIChatCompletionsClient


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
            if tool.strict:
                raise ProviderError(
                    "MiniMax does not support strict tool calling",
                    kind=ProviderErrorKind.CONFIG,
                )

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
        *,
        request: ProviderRequest,
    ) -> None:
        super().apply_options(kwargs, options, request=request)
        extra_body: dict[str, object] = dict(
            cast(Mapping[str, object], kwargs.get("extra_body", {}))
        )
        extra_body["reasoning_split"] = True
        kwargs["extra_body"] = extra_body

    def normalize_sampling(
        self, kwargs: dict[str, object], request: ProviderRequest
    ) -> None:
        kwargs.pop("temperature", None)
        kwargs.pop("top_p", None)

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
