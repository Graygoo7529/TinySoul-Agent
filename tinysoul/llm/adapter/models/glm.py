"""GLM provider adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from tinysoul.llm.config.loader import ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.tools import ToolUse

from ..base import (
    ProviderError,
    ProviderErrorKind,
    ProviderRequest,
)
from ..openai.chat import OpenAIChatAdapter
from ..openai.clients import OpenAIChatCompletionsClient
from ..openai.options import ChatOptions


class GlmOptions(ChatOptions, total=False):
    thinking: str
    do_sample: bool
    request_id: str
    user_id: str


class GlmAdapter(OpenAIChatAdapter):
    """Glm-specific option mapping."""

    output_token_field = "max_tokens"

    supports_prompt_cache_key = False

    def validate_request(self, request: ProviderRequest) -> None:
        for tool in request.tool_scope.visible_tools():
            if tool.parameters.get("type") != "object":
                raise ProviderError(
                    "GLM tool parameters root type must be object",
                    kind=ProviderErrorKind.CONFIG,
                )
            if tool.strict is not None:
                raise ProviderError(
                    "GLM does not support strict tool calling",
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
        return "auto"

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
        *,
        request: ProviderRequest,
    ) -> None:
        super().apply_options(kwargs, options, request=request)
        values = cast(GlmOptions, options or {})
        extra_body: dict[str, object] = dict(values.get("extra_body", {}))
        if "do_sample" in values:
            extra_body["do_sample"] = values["do_sample"]
        if "request_id" in values:
            extra_body["request_id"] = values["request_id"]
        if "user_id" in values:
            extra_body["user_id"] = values["user_id"]
        replay_mode = values.get("native_replay", "none")
        thinking = values.get("thinking", "enabled" if replay_mode != "none" else None)
        if thinking is not None:
            extra_body["thinking"] = {
                "type": thinking,
                "clear_thinking": replay_mode != "content",
            }
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
            adapter_kind=AdapterKind.GLM,
            completions=completions,
        )
