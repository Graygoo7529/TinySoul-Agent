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
from .clients import OpenAIResponsesClient
from .common import (
    common_create_kwargs,
    get_attr,
    model_dump_mapping,
    openai_usage,
    provider_error,
    response_metadata,
    uses_native_json_output,
)
from .payloads import apply_tools_kwargs, to_responses_input
from .response_parsing import (
    responses_stop_reason,
    responses_text,
    responses_tool_calls,
)


class OpenAIResponsesAdapter(OpenAIAdapter):
    """Reusable adapter for OpenAI Responses shaped APIs."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        adapter_kind: AdapterKind = AdapterKind.OPENAI_RESPONSES,
        responses: OpenAIResponsesClient,
        id_mapper: ToolCallIdMapper | None = None,
    ) -> None:
        provider.endpoint(adapter_spec(adapter_kind).api_mode)
        self.provider_id = provider.id
        self._cache_key_header = provider.cache_key_header
        self.adapter_kind = adapter_kind
        self._api_mode = adapter_spec(adapter_kind).api_mode
        self._id_mapper = id_mapper or DefaultToolCallIdMapper()
        self._client = responses
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
        kwargs["input"] = to_responses_input(
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
        if uses_native_json_output(request):
            kwargs["text"] = {"format": {"type": "json_object"}}
        self.apply_options(kwargs, configured_options, request=request)
        self.normalize_sampling(kwargs, request)

        try:
            response = await self._client.create(**kwargs)
        except (APIError, TimeoutError) as exc:
            raise provider_error(exc) from exc

        reasoning = self.responses_output_reasoning(response)
        output = get_attr(response, "output")
        replay_parts = (
            tuple(
                to_json_object(model_dump_mapping(part, exclude_none=True))
                for part in output
            )
            if isinstance(output, list)
            else ()
        )
        calls = responses_tool_calls(
            response, id_mapper=self._id_mapper, name_map=name_map
        )
        answer = responses_text(response)
        if (
            replay_parts
            and self.replay_mode(request) is NativeReplayMode.ENCRYPTED
            and any(
                item.get("type") == "reasoning"
                and isinstance(item.get("encrypted_content"), str)
                for item in replay_parts
            )
        ):
            reasoning = Reasoning(
                summary=reasoning.summary if reasoning is not None else None,
                native_replay=capture_replay(
                    request,
                    NativeReplayMode.ENCRYPTED,
                    replay_parts,
                    answer,
                    calls,
                ),
            )
        return RawResponse(
            answer_text=answer,
            model_id=request.model.id,
            provider_id=self.provider_id,
            tool_calls=calls,
            reasoning=reasoning,
            stop_reason=responses_stop_reason(response),
            usage=openai_usage(get_attr(response, "usage")),
            metadata=response_metadata(response),
            provider_payload=to_json_object(model_dump_mapping(response)),
        )
