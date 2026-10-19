"""Shared OpenAI API hooks; specialized adapters override only real differences."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.messages import AssistantMessage, Message
from tinysoul.llm.protocol.models import ModelCapability
from tinysoul.llm.protocol.reasoning import Reasoning, ReasoningKeep
from tinysoul.llm.protocol.tools import ToolSpec, ToolUse

from ..base import (
    ProviderError,
    ProviderErrorKind,
    ProviderFailureScope,
    ProviderRequest,
)
from ..catalog import adapter_spec
from .options import ChatOptions, OpenAIOptions, ResponsesOptions
from .payloads import to_chat_tool, to_responses_tool
from .replay import message_fingerprint
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

    def validate_identity(self, request: ProviderRequest) -> None:
        if (
            request.binding.provider_id != self.provider_id
            or request.model.adapter is not self.adapter_kind
        ):
            raise ProviderError(
                "Model binding does not match adapter",
                kind=ProviderErrorKind.CONFIG,
                scope=ProviderFailureScope.MODEL,
            )

    def validate_options(self, request: ProviderRequest) -> None:
        try:
            adapter_spec(request.model.adapter).validate_options(
                request.model.adapter_options.values, key="adapter_options"
            )
        except ConfigError as exc:
            raise ProviderError(str(exc), kind=ProviderErrorKind.CONFIG) from exc

    def validate_request(self, request: ProviderRequest) -> None:
        pass

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
            if "reasoning_context" in responses:
                _merge(kwargs, "reasoning", "context", responses["reasoning_context"])
            if "verbosity" in responses:
                _merge(kwargs, "text", "verbosity", responses["verbosity"])
            if "store" in responses:
                kwargs["store"] = responses["store"]
        else:
            chat = cast(ChatOptions, options or {})
            if effort is not None:
                kwargs["reasoning_effort"] = effort
            limit = kwargs.pop("max_completion_tokens", None)
            if limit is not None:
                kwargs[chat.get("output_token_field", self.output_token_field)] = limit
        if "prompt_cache_mode" in common:
            _merge(kwargs, "prompt_cache_options", "mode", common["prompt_cache_mode"])
        if "prompt_cache_ttl" in common:
            _merge(kwargs, "prompt_cache_options", "ttl", common["prompt_cache_ttl"])
        if common.get("reasoning_keep") == "encrypted":
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
        if cache.mode.value != "implicit":
            raise ProviderError(
                "Explicit cache breakpoints are not connected yet",
                kind=ProviderErrorKind.CONFIG,
            )
        if cache.key and self.supports_prompt_cache_key:
            kwargs["prompt_cache_key"] = cache.key
        if "prompt_cache_mode" in {
            item.id for item in adapter_spec(request.model.adapter).common_options
        }:
            _merge(kwargs, "prompt_cache_options", "mode", cache.mode.value)
            if cache.ttl is not None:
                _merge(kwargs, "prompt_cache_options", "ttl", cache.ttl.value)

    def chat_output_reasoning(self, message: object) -> Reasoning | None:
        content = chat_reasoning_content(message)
        return (
            Reasoning(content=content, summary=content) if content is not None else None
        )

    def responses_output_reasoning(self, response: object) -> Reasoning | None:
        summary = responses_reasoning_summary(response)
        return Reasoning(summary=summary)

    def chat_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
        *,
        request: ProviderRequest | None = None,
    ) -> str | None:
        if (
            adapter_reasoning_keep(options, adapter=self.adapter_kind.value)
            is ReasoningKeep.CONTENT
            and isinstance(message, AssistantMessage)
            and message.reasoning is not None
        ):
            return message.reasoning.content
        return None

    def responses_input_reasoning(
        self,
        message: Message,
        options: Mapping[str, object] | None,
        *,
        request: ProviderRequest | None = None,
    ) -> tuple[JsonObject, ...]:
        if (
            not isinstance(message, AssistantMessage)
            or message.reasoning is None
            or request is None
        ):
            return ()
        replay = message.reasoning.native_replay
        if (
            adapter_reasoning_keep(options, adapter=self.adapter_kind.value)
            is not ReasoningKeep.ENCRYPTED
            or replay is None
        ):
            return ()
        if (
            replay.api_mode,
            replay.adapter,
            replay.provider_id,
            replay.provider_model,
            replay.variant,
        ) != (
            self.api_mode,
            request.model.adapter,
            request.binding.provider_id,
            request.binding.provider_model,
            request.model.adapter_options.values.get("variant"),
        ):
            return ()
        if replay.message_fingerprint != message_fingerprint(message):
            return ()
        return replay.ordered_parts


def _merge(kwargs: dict[str, object], container: str, key: str, value: object) -> None:
    current = kwargs.get(container)
    merged = dict(current) if isinstance(current, Mapping) else {}
    merged[key] = value
    kwargs[container] = merged


def adapter_reasoning_keep(
    options: Mapping[str, object] | None, *, adapter: str
) -> ReasoningKeep:
    value = (options or {}).get("reasoning_keep", "none")
    try:
        return ReasoningKeep(value)
    except (ValueError, TypeError) as exc:
        raise ProviderError(
            f"Invalid {adapter} reasoning_keep", kind=ProviderErrorKind.CONFIG
        ) from exc
