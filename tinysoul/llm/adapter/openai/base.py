"""Shared OpenAI API hooks; specialized adapters override only real differences."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.messages import AssistantMessage, Message
from tinysoul.llm.protocol.models import ModelCapability
from tinysoul.llm.protocol.reasoning import NativeReplayMode, Reasoning
from tinysoul.llm.protocol.tools import ToolSpec, ToolUse

from ..base import ProviderRequest
from ..replay import matching_replay
from .options import ChatOptions, OpenAIOptions, ResponsesOptions
from .payloads import to_chat_tool, to_responses_tool
from .response_parsing import chat_reasoning_content, responses_reasoning_summary


class OpenAIAdapter:
    """API mapping hooks with a borrowed client and no private conversation state."""

    provider_id: str
    adapter_kind: AdapterKind
    _api_mode: ApiMode
    output_token_field = "max_completion_tokens"
    supports_prompt_cache_key = True

    @property
    def api_mode(self) -> ApiMode:
        return self._api_mode

    async def close(self) -> None:
        """The registry owns shared SDK clients, adapters only borrow them."""

    def validate_request(self, request: ProviderRequest) -> None:
        pass

    def replay_mode(self, request: ProviderRequest) -> NativeReplayMode:
        return request.model.adapter_options.native_replay_mode()

    def normalize_sampling(
        self, kwargs: dict[str, object], request: ProviderRequest
    ) -> None:
        if request.model.adapter_options.values.get("sampling") == "omit":
            kwargs.pop("temperature", None)
            kwargs.pop("top_p", None)

    def apply_options(
        self,
        kwargs: dict[str, object],
        options: Mapping[str, object] | None,
        *,
        request: ProviderRequest,
    ) -> None:
        common = cast(OpenAIOptions, options or {})
        effort = request.model.reasoning_effort
        if self.api_mode is ApiMode.OPENAI_RESPONSES:
            responses = cast(ResponsesOptions, options or {})
            if effort is not None:
                _merge(kwargs, "reasoning", "effort", effort)
            if "reasoning_summary" in responses:
                _merge(kwargs, "reasoning", "summary", responses["reasoning_summary"])
            if "reasoning_mode" in responses:
                _merge(kwargs, "reasoning", "mode", responses["reasoning_mode"])
            if "reasoning_context" in responses:
                _merge(kwargs, "reasoning", "context", responses["reasoning_context"])
            if "verbosity" in responses:
                _merge(kwargs, "text", "verbosity", responses["verbosity"])
            if "store" in responses:
                kwargs["store"] = responses["store"]
        else:
            chat = cast(ChatOptions, options or {})
            if "thinking" in chat:
                _merge(kwargs, "extra_body", "thinking", {"type": chat["thinking"]})
            if effort is not None:
                kwargs["reasoning_effort"] = effort
            limit = kwargs.pop("max_completion_tokens", None)
            if limit is not None:
                kwargs[chat.get("output_token_field", self.output_token_field)] = limit
        if request.model.supports(ModelCapability.PROMPT_CACHE):
            if "prompt_cache_mode" in common:
                _merge(
                    kwargs, "prompt_cache_options", "mode", common["prompt_cache_mode"]
                )
            if "prompt_cache_ttl" in common:
                _merge(
                    kwargs, "prompt_cache_options", "ttl", common["prompt_cache_ttl"]
                )
        if common.get("native_replay") == "encrypted":
            kwargs["include"] = ["reasoning.encrypted_content"]

    def tool_payload(self, tool: ToolSpec, *, api_mode: ApiMode) -> dict[str, object]:
        return (
            to_responses_tool(tool)
            if api_mode is ApiMode.OPENAI_RESPONSES
            else to_chat_tool(tool)
        )

    def tool_choice_payload(
        self, request: ProviderRequest, *, api_mode: ApiMode
    ) -> object | None:
        return "required" if request.tool_use is ToolUse.REQUIRED else None

    def validate_chat_finish_reason(self, finish_reason: str | None) -> None:
        pass

    def include_chat_tool_result_name(self) -> bool:
        return False

    def apply_prompt_cache(
        self, kwargs: dict[str, object], request: ProviderRequest
    ) -> None:
        cache = request.prompt_cache
        if cache is None or not request.model.supports(ModelCapability.PROMPT_CACHE):
            return
        if cache.key and self.supports_prompt_cache_key:
            kwargs["prompt_cache_key"] = cache.key

    def chat_output_reasoning(self, message: object) -> Reasoning | None:
        content = chat_reasoning_content(message)
        return Reasoning(summary=content) if content is not None else None

    def responses_output_reasoning(self, response: object) -> Reasoning | None:
        summary = responses_reasoning_summary(response)
        return Reasoning(summary=summary)

    def chat_input_reasoning(
        self,
        message: Message,
        request: ProviderRequest,
    ) -> str | None:
        if self.replay_mode(request) is NativeReplayMode.CONTENT and isinstance(
            message, AssistantMessage
        ):
            items = matching_replay(message, request, mode=NativeReplayMode.CONTENT)
            value = items[0].get("reasoning_content") if items else None
            return value if isinstance(value, str) else None
        return None

    def responses_input_reasoning(
        self,
        message: Message,
        request: ProviderRequest,
    ) -> tuple[JsonObject, ...]:
        if (
            not isinstance(message, AssistantMessage)
            or self.replay_mode(request) is not NativeReplayMode.ENCRYPTED
        ):
            return ()
        return matching_replay(message, request, mode=NativeReplayMode.ENCRYPTED)


def _merge(kwargs: dict[str, object], container: str, key: str, value: object) -> None:
    current = kwargs.get(container)
    merged = dict(current) if isinstance(current, Mapping) else {}
    merged[key] = value
    kwargs[container] = merged
