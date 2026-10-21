"""Google GenerateContent adapter with application-owned tool execution and history."""

from typing import cast

import httpx
from google.genai import errors, types
from google.genai.client import AsyncClient
from pydantic import ValidationError

from tinysoul.infra.json import to_json_object
from tinysoul.llm.config.types import ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.models import ModelCapability
from tinysoul.llm.protocol.reasoning import NativeReplayMode, Reasoning
from tinysoul.llm.protocol.responses import (
    AnswerFormat,
    RawResponse,
    ResponseStopReason,
)
from tinysoul.llm.protocol.tools import DefaultToolCallIdMapper, ToolCallRecord, ToolUse
from tinysoul.llm.protocol.usage import TokenUsage

from ..base import ProviderError, ProviderErrorKind, ProviderRequest
from ..common import status_error, validate_request
from ..replay import capture_replay
from ..tool_names import ProviderToolNameMap
from .cache import GooglePromptCacheStore
from .payloads import message_payload


class GoogleGenerateContentAdapter:
    adapter_kind = AdapterKind.GOOGLE_GENERATE_CONTENT
    api_mode = ApiMode.GOOGLE_GENERATE_CONTENT

    def __init__(self, *, provider: ProviderSpec, client: AsyncClient) -> None:
        provider.endpoint(self.api_mode)
        self.provider_id = provider.id
        self._client = client
        self._cache = GooglePromptCacheStore(client)

    async def close(self) -> None:
        await self._cache.close()

    async def invoke(self, request: ProviderRequest) -> RawResponse:
        validate_request(request, self.provider_id, self.adapter_kind)
        options = request.model.adapter_options.values
        names = ProviderToolNameMap.from_request(request)
        system, contents, prefix_count = message_payload(request, names)
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=request.max_output_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            http_options=types.HttpOptions(
                timeout=int(request.timeout_seconds * 1000)
                if request.timeout_seconds
                else None,
                extra_body=dict(request.model.adapter_options.extra_body() or {}),
            ),
        )
        if options.get("sampling") != "omit":
            config.temperature = request.temperature
            config.top_p = request.top_p
        thinking: dict[str, object] = {}
        if request.model.reasoning_effort is not None:
            thinking["thinking_level"] = request.model.reasoning_effort
        for option, field in (
            ("thinking_budget_tokens", "thinking_budget"),
            ("include_thoughts", "include_thoughts"),
        ):
            if option in options:
                thinking[field] = options[option]
        if thinking:
            # google-genai 2.31 passes this nested config through its generated
            # transformer unchanged; use wire aliases at this SDK boundary.
            wire_thinking: dict[str, object] = {}
            if "thinking_level" in thinking:
                wire_thinking["thinkingLevel"] = str(thinking["thinking_level"]).upper()
            if "thinking_budget" in thinking:
                wire_thinking["thinkingBudget"] = thinking["thinking_budget"]
            if "include_thoughts" in thinking:
                wire_thinking["includeThoughts"] = thinking["include_thoughts"]
            # The SDK's nested transformer currently leaves a raw mapping's
            # wire aliases intact, while a pydantic ThinkingConfig is emitted
            # with snake_case keys. Keep the concrete SDK field type at this
            # boundary and let the SDK serializer preserve Google's aliases.
            config.thinking_config = cast(types.ThinkingConfig, wire_thinking)
        if request.answer_format is AnswerFormat.JSON_OBJECT and request.model.supports(
            ModelCapability.JSON_OBJECT_OUTPUT
        ):
            config.response_mime_type = "application/json"
        if request.tool_use is not ToolUse.DISABLED:
            config.tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=names.to_provider_name(tool.name),
                            description=tool.description,
                            parameters_json_schema=tool.parameters,
                        )
                        for tool in request.tool_scope.visible_tools()
                    ]
                )
            ]
            forced = request.tool_scope.selection.forced_name
            config.tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="ANY"
                    if forced or request.tool_use is ToolUse.REQUIRED
                    else "AUTO",
                    allowed_function_names=[names.to_provider_name(forced)]
                    if forced
                    else None,
                )
            )
        cached_name: str | None = None
        try:
            if (
                request.model.supports(ModelCapability.PROMPT_CACHE)
                and options.get("prompt_cache_mode") == "explicit"
            ):
                if prefix_count >= len(contents):
                    raise ProviderError(
                        "Google explicit cache requires an uncached task suffix",
                        kind=ProviderErrorKind.CONFIG,
                    )
                cached_name = await self._cache.get_or_create(
                    request.binding.provider_model,
                    types.CreateCachedContentConfig(
                        contents=contents[:prefix_count],
                        system_instruction=system,
                        tools=config.tools,
                        tool_config=config.tool_config,
                        ttl=f"{options.get('prompt_cache_ttl', 600)}s",
                        http_options=config.http_options,
                    ),
                )
                config.cached_content = cached_name
                config.system_instruction = None
                config.tools = None
                config.tool_config = None
                contents = contents[prefix_count:]
            response = await self._client.models.generate_content(
                model=request.binding.provider_model,
                contents=[item for item in contents],
                config=config,
            )
        except errors.APIError as exc:
            if exc.code == 404 and cached_name:
                self._cache.invalidate(cached_name)
            raise status_error(exc.code, str(exc)) from exc
        except (httpx.TransportError, TimeoutError) as exc:
            raise ProviderError(
                "Google transport request failed", kind=ProviderErrorKind.TRANSIENT
            ) from exc
        except ValidationError as exc:
            raise ProviderError(
                "Google response could not be read", kind=ProviderErrorKind.PARSE
            ) from exc
        candidate = response.candidates[0] if response.candidates else None
        parts = (
            candidate.content.parts
            if candidate and candidate.content and candidate.content.parts
            else []
        )
        text = "".join(part.text or "" for part in parts if not part.thought)
        summary = (
            "\n".join(part.text for part in parts if part.thought and part.text) or None
        )
        mapper = DefaultToolCallIdMapper()
        calls: list[ToolCallRecord] = []
        for index, part in enumerate(parts):
            call = part.function_call
            if call is not None:
                if not call.name:
                    raise ProviderError(
                        "Google function call has no name", kind=ProviderErrorKind.PARSE
                    )
                call_id = mapper.to_tinysoul_id(
                    call.id, tool_name=call.name, index=index
                )
                calls.append(
                    ToolCallRecord(
                        id=call_id,
                        name=names.to_tinysoul_name(call.name),
                        arguments=to_json_object(call.args or {}),
                    )
                )
        items = tuple(
            to_json_object(part.model_dump(mode="json", exclude_none=True))
            for part in parts
        )
        stop = candidate.finish_reason if candidate else None
        stop_reason = {
            "STOP": ResponseStopReason.TOOL_CALLS
            if calls
            else ResponseStopReason.COMPLETE,
            "MAX_TOKENS": ResponseStopReason.OUTPUT_LIMIT,
            "SAFETY": ResponseStopReason.CONTENT_FILTER,
            "RECITATION": ResponseStopReason.CONTENT_FILTER,
            "BLOCKLIST": ResponseStopReason.CONTENT_FILTER,
            "PROHIBITED_CONTENT": ResponseStopReason.CONTENT_FILTER,
            "MALFORMED_FUNCTION_CALL": ResponseStopReason.INCOMPLETE,
        }.get(stop or "", ResponseStopReason.UNKNOWN)
        if (
            not candidate
            and response.prompt_feedback
            and response.prompt_feedback.block_reason
        ):
            stop_reason = ResponseStopReason.CONTENT_FILTER
        usage = response.usage_metadata
        output = usage.candidates_token_count if usage else None
        thoughts = usage.thoughts_token_count if usage else None
        replay = (
            capture_replay(request, NativeReplayMode.SIGNED, items, text, tuple(calls))
            if request.model.adapter_options.native_replay_mode()
            is NativeReplayMode.SIGNED
            and any(
                item.get("thought") is True
                or "thoughtSignature" in item
                or "thought_signature" in item
                or "functionCall" in item
                or "function_call" in item
                for item in items
            )
            else None
        )
        return RawResponse(
            answer_text=text,
            model_id=request.model.id,
            provider_id=self.provider_id,
            tool_calls=tuple(calls),
            reasoning=Reasoning(summary=summary, native_replay=replay)
            if summary or replay
            else None,
            stop_reason=stop_reason,
            usage=TokenUsage(
                input_tokens=usage.prompt_token_count if usage else None,
                output_tokens=(output or 0) + (thoughts or 0)
                if output is not None or thoughts is not None
                else None,
                reasoning_tokens=thoughts,
                cached_input_tokens=usage.cached_content_token_count if usage else None,
            ),
            metadata={
                "model": response.model_version,
                "api_mode": self.api_mode.value,
                "adapter": self.adapter_kind.value,
            },
        )
