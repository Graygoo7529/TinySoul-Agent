"""Aggregate Anthropic SDK streams; tools are returned, never executed."""

from typing import Protocol

from anthropic import APIConnectionError, APIError, APIStatusError
from anthropic.lib.streaming import AsyncMessageStreamManager
from httpx2 import TransportError

from tinysoul.infra.json import to_json_object
from tinysoul.llm.config.types import ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.reasoning import NativeReplayMode, Reasoning
from tinysoul.llm.protocol.responses import RawResponse, ResponseStopReason
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolUse
from tinysoul.llm.protocol.usage import TokenUsage

from ..base import ProviderError, ProviderErrorKind, ProviderRequest
from ..common import cache_key_headers, status_error, validate_request
from ..replay import capture_replay
from ..tool_names import ProviderToolNameMap
from .payloads import (
    automatic_cache_control,
    message_payload,
    prefix_fingerprint,
    tools_payload,
)


class MessagesClient(Protocol):
    def stream(self, **kwargs: object) -> AsyncMessageStreamManager[None]: ...


class AnthropicMessagesAdapter:
    adapter_kind = AdapterKind.ANTHROPIC_MESSAGES
    api_mode = ApiMode.ANTHROPIC_MESSAGES

    def __init__(self, *, provider: ProviderSpec, messages: MessagesClient) -> None:
        provider.endpoint(self.api_mode)
        self.provider_id = provider.id
        self._cache_key_header = provider.cache_key_header
        self._messages = messages

    async def close(self) -> None:
        """SDK client belongs to the registry."""

    async def invoke(self, request: ProviderRequest) -> RawResponse:
        validate_request(request, self.provider_id, self.adapter_kind)
        options = request.model.adapter_options.values
        names = ProviderToolNameMap.from_request(request)
        system, messages = message_payload(request, names)
        kwargs: dict[str, object] = {
            "model": request.binding.provider_model,
            "messages": messages,
            "max_tokens": request.max_output_tokens or 4096,
        }
        if system:
            kwargs["system"] = system
        if request.timeout_seconds is not None:
            kwargs["timeout"] = request.timeout_seconds
        thinking = options.get("thinking")
        if thinking is not None:
            value: dict[str, object] = {"type": thinking}
            budget = options.get("thinking_budget_tokens")
            if isinstance(budget, int):
                if budget >= (request.max_output_tokens or 4096):
                    raise ProviderError(
                        "Thinking budget must be below max output tokens",
                        kind=ProviderErrorKind.CONFIG,
                    )
                value["budget_tokens"] = budget
            if "thinking_display" in options:
                value["display"] = options["thinking_display"]
            kwargs["thinking"] = value
        if request.model.reasoning_effort is not None:
            kwargs["output_config"] = {"effort": request.model.reasoning_effort}
        if request.tool_use is not ToolUse.DISABLED:
            kwargs["tools"] = tools_payload(request, names)
            forced = request.tool_scope.selection.forced_name
            choice: dict[str, object] = {
                "type": "any" if request.tool_use is ToolUse.REQUIRED else "auto"
            }
            if forced:
                choice = {"type": "any"}
            if options.get("tool_choice_policy", "auto") == "auto":
                choice = {"type": "auto"}
            if thinking == "enabled" and choice["type"] != "auto":
                raise ProviderError(
                    "Manual thinking requires automatic tool choice",
                    kind=ProviderErrorKind.CONFIG,
                )
            kwargs["tool_choice"] = choice
        automatic = automatic_cache_control(request, system, messages)
        if automatic is not None:
            kwargs["cache_control"] = automatic
        headers = cache_key_headers(self._cache_key_header, request)
        if options.get("thinking_display") == "updates":
            headers["anthropic-beta"] = "thinking-display-updates-2026-08-18"
        if headers:
            kwargs["extra_headers"] = headers
        extra = dict(request.model.adapter_options.extra_body() or {})
        # The SDK has no sampling keyword arguments; the adapter still owns
        # these request fields, independently of user-supplied extra_body.
        if options.get("sampling") != "omit":
            if request.temperature is not None:
                extra["temperature"] = request.temperature
            if request.top_p is not None:
                extra["top_p"] = request.top_p
        if extra:
            kwargs["extra_body"] = extra
        try:
            async with self._messages.stream(**kwargs) as stream:
                try:
                    response = await stream.get_final_message()
                except (ValueError, AssertionError) as exc:
                    # The SDK raises for malformed deltas or an empty stream.
                    raise ProviderError(
                        "Invalid Anthropic response stream",
                        kind=ProviderErrorKind.PARSE,
                    ) from exc
        except APIStatusError as exc:
            raise _status_error(exc) from exc
        except (APIConnectionError, TransportError, TimeoutError) as exc:
            raise ProviderError(
                "Anthropic transport request failed", kind=ProviderErrorKind.TRANSIENT
            ) from exc
        except APIError as exc:
            raise ProviderError(
                "Anthropic response could not be read", kind=ProviderErrorKind.PARSE
            ) from exc
        if response.stop_reason is None:
            raise ProviderError(
                "Anthropic response stream ended before completion",
                kind=ProviderErrorKind.TRANSIENT,
            )
        text = "".join(block.text for block in response.content if block.type == "text")
        summary = (
            "\n".join(
                block.thinking for block in response.content if block.type == "thinking"
            )
            or None
        )
        try:
            calls = tuple(
                ToolCallRecord(
                    id=block.id,
                    name=names.to_tinysoul_name(block.name),
                    arguments=to_json_object(block.input),
                )
                for block in response.content
                if block.type == "tool_use"
            )
            items = tuple(
                to_json_object(block.model_dump(mode="json", exclude_none=True))
                for block in response.content
            )
        except (TypeError, ValueError) as exc:
            raise ProviderError(
                "Invalid Anthropic response blocks", kind=ProviderErrorKind.PARSE
            ) from exc
        usage = response.usage
        cached = usage.cache_read_input_tokens
        created = usage.cache_creation_input_tokens
        replay = (
            capture_replay(
                request,
                NativeReplayMode.SIGNED,
                items,
                text,
                calls,
                prefix_fingerprint=prefix_fingerprint(system, messages, request, names)
                if options.get("replay_prefix_binding") is True
                else None,
            )
            if request.model.adapter_options.native_replay_mode()
            is NativeReplayMode.SIGNED
            and any(
                item.get("type") in {"thinking", "redacted_thinking", "tool_use"}
                for item in items
            )
            else None
        )
        return RawResponse(
            answer_text=text,
            model_id=request.model.id,
            provider_id=self.provider_id,
            tool_calls=calls,
            reasoning=Reasoning(summary=summary, native_replay=replay)
            if summary or replay
            else None,
            stop_reason={
                "end_turn": ResponseStopReason.COMPLETE,
                "stop_sequence": ResponseStopReason.COMPLETE,
                "tool_use": ResponseStopReason.TOOL_CALLS,
                "max_tokens": ResponseStopReason.OUTPUT_LIMIT,
                "refusal": ResponseStopReason.CONTENT_FILTER,
                "pause_turn": ResponseStopReason.INCOMPLETE,
            }.get(response.stop_reason or "", ResponseStopReason.UNKNOWN),
            usage=TokenUsage(
                input_tokens=usage.input_tokens + (cached or 0) + (created or 0),
                output_tokens=usage.output_tokens,
                cached_input_tokens=cached,
                cache_creation_input_tokens=created,
            ),
            metadata={
                "id": response.id,
                "model": response.model,
                "api_mode": self.api_mode.value,
                "adapter": self.adapter_kind.value,
            },
        )


def _status_error(exc: APIStatusError) -> ProviderError:
    if not 200 <= exc.status_code < 300:
        return status_error(exc.status_code, str(exc))
    # SSE errors arrive after the HTTP success headers. The SDK keeps that
    # status, so classification must use the error envelope instead.
    body = exc.body
    error = body.get("error") if isinstance(body, dict) else None
    error_type = error.get("type") if isinstance(error, dict) else None
    status = (
        {
            "overloaded_error": 529,
            "api_error": 500,
            "rate_limit_error": 429,
            "timeout_error": 408,
            "authentication_error": 401,
            "permission_error": 403,
            "invalid_request_error": 400,
            "request_too_large": 413,
        }.get(error_type)
        if isinstance(error_type, str)
        else None
    )
    classified = status_error(status, str(exc))
    return ProviderError(
        f"Anthropic stream failed ({classified.kind.value})",
        kind=classified.kind,
        scope=classified.scope,
    )
