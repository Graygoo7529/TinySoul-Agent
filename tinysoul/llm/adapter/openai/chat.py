"""Reusable adapters for OpenAI SDK shaped provider APIs."""

from __future__ import annotations

from openai import APIError

from tinysoul.infra.json import to_json_object
from tinysoul.llm.adapter.catalog import adapter_spec
from tinysoul.llm.config.loader import ProviderSpec
from tinysoul.llm.execution.message_rendering import MessageContentRenderer
from tinysoul.llm.protocol.adapter_types import AdapterKind
from tinysoul.llm.protocol.reasoning import NativeReplayMode, Reasoning
from tinysoul.llm.protocol.responses import RawResponse
from tinysoul.llm.protocol.tools import DefaultToolCallIdMapper, ToolCallIdMapper

from ..base import (
    ProviderRequest,
)
from ..common import cache_key_headers, validate_request
from ..replay import capture_replay
from ..tool_names import ProviderToolNameMap
from .base import OpenAIAdapter
from .clients import OpenAIChatCompletionsClient
from .common import (
    common_create_kwargs,
    get_attr,
    model_dump_mapping,
    openai_usage,
    provider_error,
    response_metadata,
    uses_native_json_output,
)
from .payloads import apply_tools_kwargs, to_chat_messages
from .response_parsing import (
    chat_finish_reason,
    chat_stop_reason,
    chat_tool_calls,
    first_choice_message,
    message_text,
)


class OpenAIChatAdapter(OpenAIAdapter):
    """Reusable adapter for OpenAI-compatible Chat Completions APIs."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        adapter_kind: AdapterKind = AdapterKind.OPENAI_CHAT,
        completions: OpenAIChatCompletionsClient,
        id_mapper: ToolCallIdMapper | None = None,
    ) -> None:
        provider.endpoint(adapter_spec(adapter_kind).api_mode)
        self.provider_id = provider.id
        self._cache_key_header = provider.cache_key_header
        self.adapter_kind = adapter_kind
        self._api_mode = adapter_spec(adapter_kind).api_mode
        self._id_mapper = id_mapper or DefaultToolCallIdMapper()
        self._client = completions
        self._renderer = MessageContentRenderer()

    async def invoke(self, request: ProviderRequest) -> RawResponse:
        validate_request(request, self.provider_id, self.adapter_kind)
        self.validate_request(request)
        configured_options = request.model.adapter_options.values
        name_map = ProviderToolNameMap.from_request(request)
        kwargs = common_create_kwargs(request)
        headers = cache_key_headers(self._cache_key_header, request)
        if headers:
            kwargs["extra_headers"] = headers
        self.apply_prompt_cache(kwargs, request)
        kwargs["messages"] = to_chat_messages(
            request,
            adapter=self,
            renderer=self._renderer,
            id_mapper=self._id_mapper,
            name_map=name_map,
        )
        apply_tools_kwargs(
            kwargs,
            request,
            api_mode=self.api_mode,
            adapter=self,
            name_map=name_map,
        )
        max_output_tokens = kwargs.pop("max_output_tokens", None)
        if max_output_tokens is not None:
            kwargs["max_completion_tokens"] = max_output_tokens
        if uses_native_json_output(request):
            kwargs["response_format"] = {"type": "json_object"}
        self.apply_options(kwargs, configured_options, request=request)
        self.normalize_sampling(kwargs, request)

        try:
            response = await self._client.create(**kwargs)
        except (APIError, TimeoutError) as exc:
            raise provider_error(exc) from exc

        self.validate_chat_finish_reason(chat_finish_reason(response))
        message = first_choice_message(response)
        calls = chat_tool_calls(message, id_mapper=self._id_mapper, name_map=name_map)
        answer = message_text(message)
        reasoning = self.chat_output_reasoning(message)
        if reasoning is not None and reasoning.summary:
            replay = (
                capture_replay(
                    request,
                    NativeReplayMode.CONTENT,
                    ({"reasoning_content": reasoning.summary},),
                    answer,
                    calls,
                )
                if self.replay_mode(request) is NativeReplayMode.CONTENT
                else None
            )
            reasoning = Reasoning(
                summary=reasoning.summary,
                native_replay=replay,
            )
        return RawResponse(
            answer_text=answer,
            model_id=request.model.id,
            provider_id=self.provider_id,
            tool_calls=calls,
            reasoning=reasoning,
            stop_reason=chat_stop_reason(response),
            usage=openai_usage(get_attr(response, "usage")),
            metadata=response_metadata(response),
            provider_payload=to_json_object(model_dump_mapping(response)),
        )
