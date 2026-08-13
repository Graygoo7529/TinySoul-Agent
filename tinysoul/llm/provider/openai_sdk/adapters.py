"""Reusable adapters for OpenAI SDK shaped provider APIs."""

from __future__ import annotations

from typing import cast

from openai import OpenAI

from tinysoul.infra.json import to_json_object
from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
from tinysoul.llm.message_rendering import MessageContentRenderer
from tinysoul.llm.responses import RawResponse
from tinysoul.llm.tools import DefaultToolCallIdMapper, ToolCallIdMapper

from ..base import ProviderError, ProviderErrorKind, ProviderRequest
from .behavior import OpenAIAdapterBehavior
from .clients import OpenAIChatCompletionsClient, OpenAIResponsesClient
from .common import (
    common_create_kwargs,
    get_attr,
    model_dump_mapping,
    provider_error,
    response_metadata,
    uses_native_json_output,
)
from .payloads import apply_tools_kwargs, to_chat_messages, to_responses_input
from .response_parsing import (
    chat_stop_reason,
    chat_tool_calls,
    first_choice_message,
    message_text,
    responses_text,
    responses_stop_reason,
    responses_tool_calls,
)
from .tool_names import ProviderToolNameMap


class OpenAIResponsesAdapter:
    """Reusable adapter for OpenAI Responses shaped APIs."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        responses: OpenAIResponsesClient | None = None,
        behavior: OpenAIAdapterBehavior | None = None,
        id_mapper: ToolCallIdMapper | None = None,
    ) -> None:
        self.provider_id = provider.id
        self.adapter_kind = provider.adapter
        self._behavior = behavior or OpenAIAdapterBehavior()
        self._id_mapper = id_mapper or DefaultToolCallIdMapper()
        if responses is None:
            self._client: OpenAIResponsesClient = cast(
                OpenAIResponsesClient,
                OpenAI(
                    api_key=api_key,
                    base_url=provider.base_url,
                ).responses,
            )
        else:
            self._client = responses
        self._renderer = MessageContentRenderer()

    def invoke(self, request: ProviderRequest) -> RawResponse:
        _validate_adapter_identity(self, request)
        configured_options = request.model.adapter_options.values
        name_map = ProviderToolNameMap.from_request(request)
        kwargs = common_create_kwargs(request)
        self._behavior.validate_tools(request)
        self._behavior.apply_prompt_cache(kwargs, request)
        kwargs["input"] = to_responses_input(
            request,
            behavior=self._behavior,
            renderer=self._renderer,
            id_mapper=self._id_mapper,
            name_map=name_map,
        )
        apply_tools_kwargs(
            kwargs,
            request,
            api_style=ProviderApiStyle.OPENAI_RESPONSES,
            behavior=self._behavior,
            name_map=name_map,
        )
        if uses_native_json_output(request):
            kwargs["text"] = {"format": {"type": "json_object"}}
        self._behavior.apply_options(kwargs, configured_options, request=request)

        try:
            response = self._client.create(**kwargs)
        except Exception as exc:
            raise provider_error(exc) from exc

        return RawResponse(
            answer_text=responses_text(response),
            model_id=request.model.id,
            provider_id=self.provider_id,
            tool_calls=responses_tool_calls(
                response,
                id_mapper=self._id_mapper,
                name_map=name_map,
            ),
            reasoning=self._behavior.responses_output_reasoning(response),
            stop_reason=responses_stop_reason(response),
            usage=model_dump_mapping(get_attr(response, "usage")),
            metadata=response_metadata(response),
            provider_payload=to_json_object(model_dump_mapping(response)),
        )


class OpenAICompatibleChatAdapter:
    """Reusable adapter for OpenAI-compatible Chat Completions APIs."""

    def __init__(
        self,
        *,
        provider: ProviderSpec,
        api_key: str,
        completions: OpenAIChatCompletionsClient | None = None,
        behavior: OpenAIAdapterBehavior | None = None,
        id_mapper: ToolCallIdMapper | None = None,
    ) -> None:
        self.provider_id = provider.id
        self.adapter_kind = provider.adapter
        self._behavior = behavior or OpenAIAdapterBehavior()
        self._id_mapper = id_mapper or DefaultToolCallIdMapper()
        if completions is None:
            self._client: OpenAIChatCompletionsClient = cast(
                OpenAIChatCompletionsClient,
                OpenAI(
                    api_key=api_key,
                    base_url=provider.base_url,
                ).chat.completions,
            )
        else:
            self._client = completions
        self._renderer = MessageContentRenderer()

    def invoke(self, request: ProviderRequest) -> RawResponse:
        _validate_adapter_identity(self, request)
        configured_options = request.model.adapter_options.values
        name_map = ProviderToolNameMap.from_request(request)
        kwargs = common_create_kwargs(request)
        self._behavior.validate_tools(request)
        self._behavior.apply_prompt_cache(kwargs, request)
        kwargs["messages"] = to_chat_messages(
            request,
            behavior=self._behavior,
            renderer=self._renderer,
            id_mapper=self._id_mapper,
            name_map=name_map,
        )
        apply_tools_kwargs(
            kwargs,
            request,
            api_style=ProviderApiStyle.OPENAI_CHAT,
            behavior=self._behavior,
            name_map=name_map,
        )
        max_output_tokens = kwargs.pop("max_output_tokens", None)
        if max_output_tokens is not None:
            kwargs["max_completion_tokens"] = max_output_tokens
        if uses_native_json_output(request):
            kwargs["response_format"] = {"type": "json_object"}
        self._behavior.apply_options(kwargs, configured_options, request=request)

        try:
            response = self._client.create(**kwargs)
        except Exception as exc:
            raise provider_error(exc) from exc

        message = first_choice_message(response)
        return RawResponse(
            answer_text=message_text(message),
            model_id=request.model.id,
            provider_id=self.provider_id,
            tool_calls=chat_tool_calls(
                message,
                id_mapper=self._id_mapper,
                name_map=name_map,
            ),
            reasoning=self._behavior.chat_output_reasoning(message),
            stop_reason=chat_stop_reason(response),
            usage=model_dump_mapping(get_attr(response, "usage")),
            metadata=response_metadata(response),
            provider_payload=to_json_object(model_dump_mapping(response)),
        )


__all__ = [
    "OpenAICompatibleChatAdapter",
    "OpenAIResponsesAdapter",
]


def _validate_adapter_identity(
    adapter: OpenAIResponsesAdapter | OpenAICompatibleChatAdapter,
    request: ProviderRequest,
) -> None:
    if request.model.adapter is adapter.adapter_kind:
        return
    raise ProviderError(
        "Model adapter does not match provider adapter",
        kind=ProviderErrorKind.CONFIG,
    )
