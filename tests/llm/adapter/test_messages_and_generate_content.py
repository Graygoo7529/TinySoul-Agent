"""Real SDK serialization through local HTTP transports, without provider credentials."""

import json
from dataclasses import replace
from typing import Any, cast

import httpx
import httpx2
import pytest
from anthropic import AsyncAnthropic
from google import genai
from google.genai import types

from tinysoul.llm.adapter.anthropic.messages import (
    AnthropicMessagesAdapter,
    MessagesClient,
)
from tinysoul.llm.adapter.base import ProviderError, ProviderErrorKind, ProviderRequest
from tinysoul.llm.adapter.google.generate_content import GoogleGenerateContentAdapter
from tinysoul.llm.config.types import ProviderEndpoint, ProviderSpec
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.cache import PromptCache
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    MessageStack,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.protocol.models import (
    AdapterOptions,
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
)
from tinysoul.llm.protocol.responses import AnswerFormat
from tinysoul.llm.protocol.tools import ToolKind, ToolScope, ToolSpec, ToolUse

pytestmark = pytest.mark.anyio


def provider(mode: ApiMode) -> ProviderSpec:
    return ProviderSpec(
        id="test",
        api_key_envs=("TEST_KEY",),
        endpoints=(ProviderEndpoint(mode, "https://provider.test"),),
    )


def request(mode: ApiMode, **options: object) -> ProviderRequest:
    binding = ModelProviderBinding("test", "model-latest")
    model = ModelSpec(
        id="test-latest",
        providers=(binding,),
        context_window_tokens=100000,
        adapter=AdapterKind(mode.value),
        capabilities=frozenset(ModelCapability),
        adapter_options=AdapterOptions(options),
    )
    return ProviderRequest(
        model=model,
        binding=binding,
        answer_format=AnswerFormat.TEXT,
        messages=MessageStack.of(
            SystemMessage.from_text("Identity"),
            UserMessage.from_text("Stable background"),
            UserMessage.from_text("Task"),
        ),
        tool_use=ToolUse.OPTIONAL,
        tool_scope=ToolScope(
            tools=(
                ToolSpec(
                    kind=ToolKind.CONTROL,
                    name="core.inspect",
                    description="Read",
                    parameters={"type": "object", "properties": {}},
                ),
            )
        ),
        max_output_tokens=4096,
        timeout_seconds=15,
    )


@pytest.mark.parametrize("summary", ["Plan", ""])
async def test_anthropic_sdk_signed_tool_roundtrip_and_cache(summary: str) -> None:
    bodies: list[dict] = []
    blocks = [
        {"type": "thinking", "thinking": summary, "signature": "opaque-signature"},
        {"type": "tool_use", "id": "call_1", "name": "core_inspect", "input": {}},
    ]

    def respond(req: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(req.content))
        assert req.headers["x-api-key"] == "test-key"
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "model-latest",
                "content": blocks,
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 40,
                },
            },
        )

    async with AsyncAnthropic(
        api_key="test-key",
        base_url="https://provider.test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    ) as sdk:
        adapter = AnthropicMessagesAdapter(
            provider=provider(ApiMode.ANTHROPIC_MESSAGES),
            messages=cast(MessagesClient, sdk.messages),
        )
        first = request(
            ApiMode.ANTHROPIC_MESSAGES,
            thinking="adaptive",
            thinking_display="omitted",
            native_replay="signed",
            prompt_cache_mode="explicit",
            prompt_cache_ttl="1h",
        )
        first = replace(first, prompt_cache=PromptCache(breakpoint_message_index=1))
        response = await adapter.invoke(first)
        assert response.usage.input_tokens == 145
        assert response.reasoning is not None
        assert response.reasoning.native_replay is not None
        assert response.reasoning.summary == (summary or None)
        assert response.reasoning.native_replay.ordered_items == tuple(blocks)
        assert bodies[0]["messages"][0]["content"][0]["cache_control"] == {
            "type": "ephemeral",
            "ttl": "1h",
        }
        assert bodies[0]["thinking"] == {"type": "adaptive", "display": "omitted"}
        continuation = replace(
            first,
            messages=MessageStack.of(
                UserMessage.from_text("Task"),
                AssistantMessage.from_text(
                    response.answer_text,
                    reasoning=response.reasoning,
                    tool_calls=response.tool_calls,
                ),
                ToolResultMessage.from_text(
                    call_id="call_1", tool_name="core.inspect", text="Result"
                ),
            ),
            prompt_cache=None,
            model=replace(
                first.model,
                adapter_options=AdapterOptions(
                    {"thinking": "adaptive", "native_replay": "signed"}
                ),
            ),
        )
        await adapter.invoke(continuation)
        assert bodies[1]["messages"][1]["content"] == blocks
        assert bodies[1]["messages"][2]["content"][0]["tool_use_id"] == "call_1"
        edited = replace(
            continuation,
            messages=MessageStack.of(
                UserMessage.from_text("Task"),
                AssistantMessage.from_text(
                    "Changed",
                    reasoning=response.reasoning,
                    tool_calls=response.tool_calls,
                ),
                ToolResultMessage.from_text(
                    call_id="call_1", tool_name="core.inspect", text="Result"
                ),
            ),
        )
        await adapter.invoke(edited)
        assert bodies[2]["messages"][1]["content"][0]["text"].startswith("Changed")
        assert bodies[2]["messages"][2]["content"][0]["text"].endswith("Result")
        # A later edited response may reuse a provider call ID. Its result must
        # not attach to an earlier, valid native exchange with the same ID.
        repeated = replace(
            continuation,
            messages=MessageStack.of(
                *continuation.messages.messages,
                *edited.messages.messages[1:],
            ),
        )
        await adapter.invoke(repeated)
        assert bodies[-1]["messages"][3]["content"][0]["type"] == "text"
        assert bodies[-1]["messages"][4]["content"][0]["type"] == "text"
        alias_conflict = replace(
            continuation,
            tool_scope=ToolScope(
                tools=(
                    *continuation.tool_scope.tools,
                    ToolSpec(
                        kind=ToolKind.CONTROL,
                        name="core_inspect",
                        description="Other",
                        parameters={"type": "object"},
                    ),
                )
            ),
        )
        await adapter.invoke(alias_conflict)
        assert bodies[-1]["messages"][1]["content"][0]["type"] == "text"
        assert bodies[-1]["messages"][2]["content"][0]["type"] == "text"


@pytest.mark.parametrize("summary", ["Plan", ""])
async def test_google_sdk_signature_parts_cache_and_usage(summary: str) -> None:
    bodies: list[tuple[str, dict]] = []
    parts = ([{"text": summary, "thought": True}] if summary else []) + [
        {
            "functionCall": {"name": "core_inspect", "args": {}},
            "thoughtSignature": "c2lnbmF0dXJl",
        }
    ]

    def respond(req: Any) -> Any:
        body = json.loads(req.content)
        bodies.append((req.url.path, body))
        assert req.headers["x-goog-api-key"] == "test-key"
        if req.url.path.endswith("/cachedContents"):
            return httpx.Response(
                200,
                json={
                    "name": "cachedContents/prefix",
                    "expireTime": "2099-01-01T00:00:00Z",
                },
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": parts},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 10,
                    "thoughtsTokenCount": 7,
                    "cachedContentTokenCount": 80,
                },
                "modelVersion": "model-latest",
            },
        )

    sdk = genai.Client(
        api_key="test-key",
        http_options=types.HttpOptions(
            base_url="https://provider.test",
            api_version="v1beta",
            retry_options=types.HttpRetryOptions(attempts=1),
            httpx_async_client=httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            ),
        ),
    )
    adapter = GoogleGenerateContentAdapter(
        provider=provider(ApiMode.GOOGLE_GENERATE_CONTENT), client=sdk.aio
    )
    try:
        first = request(
            ApiMode.GOOGLE_GENERATE_CONTENT,
            reasoning_efforts=["high"],
            include_thoughts=True,
            native_replay="signed",
            prompt_cache_mode="explicit",
            prompt_cache_ttl=600,
        )
        first = replace(
            first,
            model=replace(first.model, reasoning_effort="high"),
            prompt_cache=PromptCache(breakpoint_message_index=1),
        )
        response = await adapter.invoke(first)
        await adapter.invoke(first)
        assert len(bodies) == 3  # one cache create, two generations
        creation, generation = bodies[0][1], bodies[1][1]
        assert creation["ttl"] == "600s"
        assert creation["systemInstruction"]["parts"][0]["text"] == "Identity"
        assert generation["contents"] == [{"role": "user", "parts": [{"text": "Task"}]}]
        assert "systemInstruction" not in generation and "tools" not in generation
        assert generation["cachedContent"] == "cachedContents/prefix"
        assert (
            generation["generationConfig"]["thinkingConfig"].get("thinkingLevel")
            == "HIGH"
        ), generation
        assert response.usage.output_tokens == 17
        assert response.usage.reasoning_tokens == 7
        assert (
            response.reasoning is not None
            and response.reasoning.native_replay is not None
        )
        assert response.reasoning.summary == (summary or None)
        continuation = replace(
            first,
            prompt_cache=None,
            model=replace(
                first.model,
                adapter_options=AdapterOptions(
                    {"include_thoughts": False, "native_replay": "signed"}
                ),
                reasoning_effort=None,
            ),
            messages=MessageStack.of(
                UserMessage.from_text("Task"),
                AssistantMessage.from_text(
                    response.answer_text,
                    reasoning=response.reasoning,
                    tool_calls=response.tool_calls,
                ),
                ToolResultMessage.from_text(
                    call_id=response.tool_calls[0].id,
                    tool_name="core.inspect",
                    text="Result",
                ),
            ),
        )
        await adapter.invoke(continuation)
        actual = bodies[-1][1]["contents"]
        assert actual[1]["parts"] == parts
        assert "id" not in actual[2]["parts"][0]["functionResponse"]
        assert actual[2]["parts"][0]["functionResponse"]["name"] == "core_inspect"
        repeated = replace(
            continuation,
            messages=MessageStack.of(
                *continuation.messages.messages,
                AssistantMessage.from_text(
                    "Edited",
                    reasoning=response.reasoning,
                    tool_calls=response.tool_calls,
                ),
                ToolResultMessage.from_text(
                    call_id=response.tool_calls[0].id,
                    tool_name="core.inspect",
                    text="Second result",
                ),
            ),
        )
        await adapter.invoke(repeated)
        assert "functionCall" not in bodies[-1][1]["contents"][3]["parts"][0]
        assert "functionResponse" not in bodies[-1][1]["contents"][4]["parts"][0]
        alias_conflict = replace(
            continuation,
            tool_scope=ToolScope(
                tools=(
                    *continuation.tool_scope.tools,
                    ToolSpec(
                        kind=ToolKind.CONTROL,
                        name="core_inspect",
                        description="Other",
                        parameters={"type": "object"},
                    ),
                )
            ),
        )
        await adapter.invoke(alias_conflict)
        assert "functionCall" not in bodies[-1][1]["contents"][1]["parts"][0]
        assert "functionResponse" not in bodies[-1][1]["contents"][2]["parts"][0]
    finally:
        await adapter.close()
        await sdk.aio.aclose()
        sdk.close()


async def test_google_cache_rebuilds_after_expiry_and_remote_eviction() -> None:
    created = 0
    used: list[str] = []

    def respond(req: httpx.Request) -> httpx.Response:
        nonlocal created
        body = json.loads(req.content)
        if req.url.path.endswith("/cachedContents"):
            created += 1
            return httpx.Response(
                200,
                json={
                    "name": f"cachedContents/{created}",
                    "expireTime": "2000-01-01T00:00:00Z"
                    if created == 1
                    else "2099-01-01T00:00:00Z",
                },
            )
        used.append(body["cachedContent"])
        if len(used) == 3:
            return httpx.Response(
                404,
                json={
                    "error": {
                        "code": 404,
                        "message": "Cache expired",
                        "status": "NOT_FOUND",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "ok"}]},
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    sdk = genai.Client(
        api_key="test",
        http_options=types.HttpOptions(
            base_url="https://provider.test",
            retry_options=types.HttpRetryOptions(attempts=1),
            httpx_async_client=httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            ),
        ),
    )
    adapter = GoogleGenerateContentAdapter(
        provider=provider(ApiMode.GOOGLE_GENERATE_CONTENT), client=sdk.aio
    )
    invocation = replace(
        request(ApiMode.GOOGLE_GENERATE_CONTENT, prompt_cache_mode="explicit"),
        prompt_cache=PromptCache(breakpoint_message_index=1),
    )
    try:
        await adapter.invoke(invocation)
        await adapter.invoke(invocation)
        with pytest.raises(ProviderError):
            await adapter.invoke(invocation)
        await adapter.invoke(invocation)
        assert used == [
            "cachedContents/1",
            "cachedContents/2",
            "cachedContents/2",
            "cachedContents/3",
        ]
        await adapter.close()
        assert (
            created == 3
        )  # Closing does not delete remote resources; TTL owns cleanup.
    finally:
        await sdk.aio.aclose()
        sdk.close()


async def test_anthropic_manual_thinking_and_automatic_cache_use_sdk_fields() -> None:
    bodies: list[dict[str, object]] = []

    def respond(req: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(req.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "model-latest",
                "content": [{"type": "text", "text": '{"ok":true}'}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    async with AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    ) as sdk:
        adapter = AnthropicMessagesAdapter(
            provider=provider(ApiMode.ANTHROPIC_MESSAGES),
            messages=cast(MessagesClient, sdk.messages),
        )
        invocation = replace(
            request(
                ApiMode.ANTHROPIC_MESSAGES,
                thinking="enabled",
                thinking_budget_tokens=1024,
                prompt_cache_mode="automatic",
                prompt_cache_ttl="5m",
                sampling="omit",
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            temperature=0.7,
            top_p=0.9,
            prompt_cache=PromptCache(key="task-key"),
        )
        response = await adapter.invoke(invocation)
        assert response.answer_text == '{"ok":true}'
        assert bodies[0]["thinking"] == {"type": "enabled", "budget_tokens": 1024}
        assert bodies[0]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
        assert not {
            "prompt_cache_key",
            "temperature",
            "top_p",
            "output_config",
        }.intersection(bodies[0])
        # No unconstrained JSON schema is invented; the task's prompt and
        # ResponseInterpreter retain the JSON-object contract.
        no_cache = replace(
            invocation,
            model=replace(
                invocation.model,
                capabilities=invocation.model.capabilities
                - {ModelCapability.PROMPT_CACHE},
            ),
        )
        await adapter.invoke(no_cache)
        assert "cache_control" not in bodies[-1]


async def test_google_implicit_cache_budget_and_json_do_not_create_resources() -> None:
    bodies: list[dict[str, object]] = []

    def respond(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith(":generateContent")
        bodies.append(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": '{"ok":true}'}],
                        },
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    sdk = genai.Client(
        api_key="test",
        http_options=types.HttpOptions(
            httpx_async_client=httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            ),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    adapter = GoogleGenerateContentAdapter(
        provider=provider(ApiMode.GOOGLE_GENERATE_CONTENT), client=sdk.aio
    )
    try:
        invocation = replace(
            request(
                ApiMode.GOOGLE_GENERATE_CONTENT,
                thinking_budget_tokens=-1,
                include_thoughts=False,
                prompt_cache_mode="implicit",
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            prompt_cache=PromptCache(key="ignored"),
        )
        await adapter.invoke(invocation)
        assert bodies[0]["generationConfig"] == {
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": -1, "includeThoughts": False},
        }
        assert "cachedContent" not in bodies[0]
    finally:
        await adapter.close()
        await sdk.aio.aclose()
        sdk.close()


@pytest.mark.parametrize(
    "mode", [ApiMode.ANTHROPIC_MESSAGES, ApiMode.GOOGLE_GENERATE_CONTENT]
)
async def test_sdk_error_is_classified_without_provider_body(mode: ApiMode) -> None:
    count = 0

    def respond(req: Any) -> Any:
        nonlocal count
        count += 1
        return (httpx2 if mode is ApiMode.ANTHROPIC_MESSAGES else httpx).Response(
            429,
            json={
                "error": {
                    "message": "private provider detail",
                    "code": 429,
                    "type": "rate_limit_error",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )

    http = httpx2 if mode is ApiMode.ANTHROPIC_MESSAGES else httpx
    transport: Any = cast(Any, http).AsyncClient(
        transport=cast(Any, http).MockTransport(respond)
    )
    if mode is ApiMode.ANTHROPIC_MESSAGES:
        sdk = AsyncAnthropic(api_key="test", http_client=transport, max_retries=0)
        adapter = AnthropicMessagesAdapter(
            provider=provider(mode), messages=cast(MessagesClient, sdk.messages)
        )
        close = sdk.close
    else:
        google = genai.Client(
            api_key="test",
            http_options=types.HttpOptions(
                httpx_async_client=transport,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        adapter = GoogleGenerateContentAdapter(
            provider=provider(mode), client=google.aio
        )
        close = google.aio.aclose
    try:
        with pytest.raises(ProviderError) as exc:
            await adapter.invoke(request(mode))
        assert exc.value.kind is ProviderErrorKind.TRANSIENT
        assert "private provider detail" not in str(exc.value)
        assert count == 1
    finally:
        await close()
