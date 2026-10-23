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

from tests.support.anthropic import anthropic_sse_response
from tinysoul.llm.adapter.anthropic.messages import (
    AnthropicMessagesAdapter,
    MessagesClient,
)
from tinysoul.llm.adapter.base import ProviderError, ProviderErrorKind, ProviderRequest
from tinysoul.llm.adapter.google.client import GoogleClient
from tinysoul.llm.adapter.google.generate_content import GoogleGenerateContentAdapter
from tinysoul.llm.adapter.registry import ProviderRegistry
from tinysoul.llm.config.types import ProviderEndpoint, ProviderSpec
from tinysoul.llm.execution.model_chain import TaskSpecTable
from tinysoul.llm.execution.registry import ModelRegistry
from tinysoul.llm.execution.task import LLMTaskRunner
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.cache import PromptCache, PromptCacheBreakpoint
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
from tinysoul.llm.protocol.requests import CallSettings, TaskCall
from tinysoul.llm.protocol.responses import AnswerFormat, ResponseStopReason
from tinysoul.llm.protocol.routing import ModelChain, RetryPolicy, TaskSpec
from tinysoul.llm.protocol.tools import ToolKind, ToolScope, ToolSpec, ToolUse

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("identity", [None, "Explicit-Agent/1"])
async def test_google_owned_client_preserves_http_identity(monkeypatch, identity):
    seen = []

    async def respond(_transport, request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}
                ]
            },
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", respond)
    client = GoogleClient(
        api_key="test",
        base_url="https://google.test",
        api_version="v1beta",
        headers={"User-Agent": identity} if identity else {},
    )
    try:
        response = await client.sdk.aio.models.generate_content(
            model="model", contents="Hello"
        )
        assert response.text == "ok"
        assert seen[0] == identity if identity else seen[0].startswith("TinySoul-Agent")
    finally:
        await client.close()


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
    headers: list[str | None] = []
    blocks = [
        {"type": "thinking", "thinking": summary, "signature": "opaque-signature"},
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "core_inspect",
            "input": {"ref": "test"},
        },
    ]

    def respond(req: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(req.content))
        headers.append(req.headers.get("x-session"))
        assert req.headers["x-api-key"] == "test-key"
        return anthropic_sse_response(
            {
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
            }
        )

    async with AsyncAnthropic(
        api_key="test-key",
        base_url="https://provider.test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    ) as sdk:
        adapter = AnthropicMessagesAdapter(
            provider=replace(
                provider(ApiMode.ANTHROPIC_MESSAGES), cache_key_header="x-session"
            ),
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
        first = replace(
            first,
            prompt_cache=PromptCache(
                key="turn-key", breakpoints=(PromptCacheBreakpoint("background", 1),)
            ),
        )
        response = await adapter.invoke(first)
        assert headers[0] == "turn-key"
        assert response.stop_reason is ResponseStopReason.TOOL_CALLS
        assert response.tool_calls[0].arguments == {"ref": "test"}
        assert response.usage.input_tokens == 145
        assert response.usage.output_tokens == 20
        assert response.usage.cached_input_tokens == 100
        assert response.usage.cache_creation_input_tokens == 40
        assert response.reasoning is not None
        assert response.reasoning.native_replay is not None
        assert response.reasoning.summary == (summary or None)
        assert response.reasoning.native_replay.ordered_items == tuple(blocks)
        messages = bodies[0]["messages"]
        assert isinstance(messages, list)
        assert messages[0]["content"][0]["cache_control"] == {
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
        assert bodies[2]["messages"][2]["content"][0]["type"] == "tool_result"
        # A later edited response may reuse a provider call ID. Its result must
        # retain the new text and attach its result to the new tool exchange.
        repeated = replace(
            continuation,
            messages=MessageStack.of(
                *continuation.messages.messages,
                *edited.messages.messages[1:],
            ),
        )
        await adapter.invoke(repeated)
        assert bodies[-1]["messages"][3]["content"][0]["type"] == "text"
        assert bodies[-1]["messages"][4]["content"][0]["type"] == "tool_result"
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
        assert bodies[-1]["messages"][1]["content"][0]["type"] == "tool_use"
        assert bodies[-1]["messages"][1]["content"][0]["name"] != "core_inspect"
        assert bodies[-1]["messages"][2]["content"][0]["type"] == "tool_result"


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
        if len(bodies) <= 3:
            assert req.headers["x-session"] == "turn-key"
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
        provider=replace(
            provider(ApiMode.GOOGLE_GENERATE_CONTENT), cache_key_header="x-session"
        ),
        client=sdk.aio,
    )
    try:
        first = request(
            ApiMode.GOOGLE_GENERATE_CONTENT,
            choices={"reasoning_effort": ["high"]},
            include_thoughts=True,
            native_replay="signed",
            prompt_cache_mode="explicit",
            prompt_cache_ttl=600,
        )
        first = replace(
            first,
            model=replace(first.model, reasoning_effort="high"),
            prompt_cache=PromptCache(
                key="turn-key", breakpoints=(PromptCacheBreakpoint("background", 1),)
            ),
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
        # A boundary at the assistant call retreats before the exchange, so the
        # signed call and its result both remain in the generation suffix.
        split = replace(
            continuation,
            model=replace(
                continuation.model,
                adapter_options=AdapterOptions(
                    {
                        **continuation.model.adapter_options.values,
                        "prompt_cache_mode": "explicit",
                        "prompt_cache_boundaries": ["trace"],
                    }
                ),
            ),
            prompt_cache=PromptCache(breakpoints=(PromptCacheBreakpoint("trace", 1),)),
        )
        await adapter.invoke(split)
        assert bodies[-2][0].endswith("/cachedContents")
        assert bodies[-2][1]["contents"] == actual[:1]
        assert bodies[-1][1]["contents"] == actual[1:]
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
        prompt_cache=PromptCache(breakpoints=(PromptCacheBreakpoint("background", 1),)),
    )
    try:
        await adapter.invoke(invocation)
        await adapter.invoke(invocation)
        runner = LLMTaskRunner(
            models=ModelRegistry([invocation.model]),
            providers=ProviderRegistry([adapter]),
            tasks=TaskSpecTable(
                [
                    TaskSpec(
                        profile="cache-test",
                        chain=ModelChain(
                            "cache-test",
                            (invocation.model.id,),
                            RetryPolicy(max_cycles=1),
                        ),
                        settings=CallSettings(
                            answer_format=AnswerFormat.TEXT,
                            tool_use=ToolUse.OPTIONAL,
                            max_output_tokens=4096,
                        ),
                    )
                ]
            ),
        )
        result = await runner.invoke(
            TaskCall(
                profile="cache-test",
                messages=invocation.messages,
                tool_scope=invocation.tool_scope,
                prompt_cache=invocation.prompt_cache,
            )
        )
        assert result.answer is not None
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
        return anthropic_sse_response(
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "model-latest",
                "content": [{"type": "text", "text": '{"ok":true}'}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
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
                prompt_cache_boundaries=["background"],
                prompt_cache_ttls={"background": "1h"},
                sampling="omit",
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            temperature=0.7,
            top_p=0.9,
            prompt_cache=PromptCache(
                key="task-key",
                breakpoints=(PromptCacheBreakpoint("background", 1),),
            ),
        )
        response = await adapter.invoke(invocation)
        assert response.answer_text == '{"ok":true}'
        assert bodies[0]["thinking"] == {"type": "enabled", "budget_tokens": 1024}
        assert bodies[0]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
        messages = bodies[0]["messages"]
        assert isinstance(messages, list)
        assert messages[0]["content"][0]["cache_control"] == {
            "type": "ephemeral",
            "ttl": "1h",
        }
        assert not {
            "prompt_cache_key",
            "temperature",
            "top_p",
            "output_config",
        }.intersection(bodies[0])
        # No unconstrained JSON schema is invented; the task's prompt and
        # ResponseInterpreter retain the JSON-object contract.
        coincident = replace(
            invocation,
            prompt_cache=PromptCache(
                breakpoints=(PromptCacheBreakpoint("background", 2),)
            ),
        )
        await adapter.invoke(coincident)
        assert "cache_control" not in bodies[-1]
        merged_messages = bodies[-1]["messages"]
        assert isinstance(merged_messages, list)
        assert merged_messages[-1]["content"][-1]["cache_control"] == {
            "type": "ephemeral",
            "ttl": "1h",
        }
        inverted_ttls = replace(
            invocation,
            model=replace(
                invocation.model,
                adapter_options=AdapterOptions(
                    {
                        **invocation.model.adapter_options.values,
                        "prompt_cache_ttl": "1h",
                        "prompt_cache_ttls": {"background": "5m"},
                    }
                ),
            ),
        )
        before = len(bodies)
        with pytest.raises(ProviderError) as invalid:
            await adapter.invoke(inverted_ttls)
        assert invalid.value.kind is ProviderErrorKind.CONFIG
        assert len(bodies) == before
        no_cache = replace(
            invocation,
            model=replace(
                invocation.model,
                capabilities=invocation.model.capabilities
                - {ModelCapability.PROMPT_CACHE},
                adapter_options=AdapterOptions(
                    {
                        key: value
                        for key, value in invocation.model.adapter_options.values.items()
                        if not key.startswith("prompt_cache_")
                    }
                ),
            ),
        )
        await adapter.invoke(no_cache)
        assert "cache_control" not in bodies[-1]


@pytest.mark.parametrize(
    ("thinking", "display", "effort"),
    [
        ("adaptive", "updates", "high"),
        ("between_tools", None, "high"),
        ("disabled", None, None),
    ],
)
async def test_anthropic_sdk_thinking_modes_and_display_header(
    thinking: str,
    display: str | None,
    effort: str | None,
) -> None:
    captured: list[httpx2.Request] = []

    def respond(incoming: httpx2.Request) -> httpx2.Response:
        captured.append(incoming)
        return anthropic_sse_response(
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "model-latest",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )

    options: dict[str, object] = {"thinking": thinking}
    if display is not None:
        options["thinking_display"] = display
    if effort is not None:
        options["choices"] = {"reasoning_effort": [effort]}
    invocation = request(ApiMode.ANTHROPIC_MESSAGES, **options)
    invocation = replace(
        invocation,
        model=replace(invocation.model, reasoning_effort=effort),
        tool_use=ToolUse.REQUIRED,
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
        await adapter.invoke(invocation)
    body = json.loads(captured[0].content)
    assert body["thinking"] == {
        "type": thinking,
        **({"display": display} if display else {}),
    }
    assert body["tool_choice"] == {"type": "auto"}
    assert body.get("output_config") == ({"effort": effort} if effort else None)
    assert not {"choices", "choice_rules"}.intersection(body)
    assert captured[0].headers.get("anthropic-beta") == (
        "thinking-display-updates-2026-08-18" if display == "updates" else None
    )


@pytest.mark.parametrize("cache_mode", [None, "implicit"])
async def test_google_implicit_cache_budget_and_json_do_not_create_resources(
    cache_mode: str | None,
) -> None:
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
                **({"prompt_cache_mode": cache_mode} if cache_mode else {}),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            prompt_cache=PromptCache(
                key="ignored",
                breakpoints=(PromptCacheBreakpoint("background", 1),),
            ),
        )
        await adapter.invoke(invocation)
        assert bodies[0]["generationConfig"] == {
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": -1, "includeThoughts": False},
        }
        assert "cachedContent" not in bodies[0]
        assert "Stable background" in json.dumps(bodies[0]["contents"])
        assert "Task" in json.dumps(bodies[0]["contents"])
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
