import asyncio
import json
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import cast

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI

from tinysoul.infra.config import ConfigError
from tinysoul.llm.adapter.base import ProviderRequest
from tinysoul.llm.adapter.catalog import adapter_spec, adapter_specs_json
from tinysoul.llm.adapter.factory import build_provider_registry
from tinysoul.llm.adapter.models.glm import GlmAdapter
from tinysoul.llm.adapter.models.kimi import KimiAdapter
from tinysoul.llm.adapter.models.minimax import MiniMaxAdapter
from tinysoul.llm.adapter.openai.chat import OpenAIChatAdapter
from tinysoul.llm.adapter.openai.clients import (
    OpenAIChatCompletionsClient,
    OpenAIResponsesClient,
)
from tinysoul.llm.adapter.openai.responses import OpenAIResponsesAdapter
from tinysoul.llm.config.types import ProviderEndpoint, ProviderSpec
from tinysoul.llm.execution.registry import ModelRegistry
from tinysoul.llm.protocol.adapter_types import AdapterKind, ApiMode
from tinysoul.llm.protocol.cache import PromptCache, PromptCacheBreakpoint
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    MessageStack,
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


@dataclass
class Client:
    response: object
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


def provider() -> ProviderSpec:
    return ProviderSpec(
        "gateway",
        (
            ProviderEndpoint(ApiMode.OPENAI_CHAT, "https://example.test/chat"),
            ProviderEndpoint(
                ApiMode.OPENAI_RESPONSES,
                "https://example.test/responses",
                headers={"X-Route": "responses"},
                header_refs={"X-Secret": "ROUTE_TOKEN"},
            ),
            ProviderEndpoint(
                ApiMode.ANTHROPIC_MESSAGES, "https://example.test/messages"
            ),
        ),
        ("FIRST_KEY", "SECOND_KEY"),
        headers={"X-Route": "shared", "X-App": "TinySoul"},
    )


def model(kind: AdapterKind, options: dict[str, object] | None = None) -> ModelSpec:
    return ModelSpec(
        kind.value,
        (ModelProviderBinding("gateway", "vendor/version"),),
        262144,
        adapter=kind,
        adapter_options=AdapterOptions(options or {}),
    )


def request(spec: ModelSpec, messages: MessageStack | None = None) -> ProviderRequest:
    return ProviderRequest(
        spec,
        spec.providers[0],
        messages or MessageStack.of(UserMessage.from_text("hello")),
        AnswerFormat.TEXT,
    )


async def test_cache_header_is_per_request_without_cache_capability() -> None:
    client = Client(SimpleNamespace(output=[], output_text="ok"))
    adapter = OpenAIResponsesAdapter(
        provider=replace(provider(), cache_key_header="x-session"),
        responses=cast(OpenAIResponsesClient, client),
    )
    base = request(model(AdapterKind.OPENAI_RESPONSES))
    await asyncio.gather(
        *(
            adapter.invoke(
                replace(base, prompt_cache=PromptCache(key=key) if key else None)
            )
            for key in ("turn-one", "turn-two", None, "turn-one")
        )
    )
    assert [call.get("extra_headers") for call in client.calls] == [
        {"x-session": "turn-one"},
        {"x-session": "turn-two"},
        None,
        {"x-session": "turn-one"},
    ]


def test_dynamic_header_rejects_case_insensitive_static_collision() -> None:
    from tinysoul.llm.errors import LLMContractError

    with pytest.raises(LLMContractError, match="conflicts"):
        replace(provider(), cache_key_header="x-ROUTE")


async def test_registry_reuses_mode_clients_and_owns_close_once(monkeypatch) -> None:
    created: list[dict[str, object]] = []
    closed: list[object] = []

    class SDK:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.responses = Client(SimpleNamespace(output=[], output_text="ok"))
            self.chat = SimpleNamespace(completions=Client(None))

        async def close(self):
            closed.append(self)

    monkeypatch.setattr("tinysoul.llm.adapter.factory.AsyncOpenAI", SDK)
    models = ModelRegistry(
        [
            model(kind)
            for kind in (
                AdapterKind.OPENAI_CHAT,
                AdapterKind.DEEPSEEK,
                AdapterKind.OPENAI_RESPONSES,
                AdapterKind.GPT,
                AdapterKind.ANTHROPIC_MESSAGES,
            )
        ]
    )
    registry = await build_provider_registry(
        (provider(),),
        models=models,
        env={"SECOND_KEY": "api-secret", "ROUTE_TOKEN": "route-secret"},
    )
    assert len(created) == 2
    assert all(
        item["max_retries"] == 0 and item["api_key"] == "api-secret" for item in created
    )
    headers = next(
        item for item in created if item["base_url"] == "https://example.test/responses"
    )["default_headers"]
    assert isinstance(headers, dict)
    assert headers["x-route"] == "responses"
    assert headers["x-app"] == "TinySoul"
    assert headers["x-secret"] == "route-secret"
    assert headers["user-agent"].startswith("TinySoul-Agent")
    assert registry.has("gateway", AdapterKind.GPT)
    assert registry.has("gateway", AdapterKind.DEEPSEEK)
    assert not registry.has("gateway", AdapterKind.KIMI)
    assert registry.has("gateway", AdapterKind.ANTHROPIC_MESSAGES)
    await registry.close()
    await registry.close()
    assert len(closed) == 2


@pytest.mark.parametrize(
    "kind", [AdapterKind.OPENAI_CHAT, AdapterKind.OPENAI_RESPONSES, AdapterKind.MINIMAX]
)
async def test_generic_adapters_map_effort_sampling_and_extensions(
    kind: AdapterKind,
) -> None:
    client = Client(
        SimpleNamespace(
            output=[],
            output_text="ok",
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        )
    )
    spec = replace(
        model(
            kind,
            {
                "choices": {"reasoning_effort": ["high", "xhigh"]},
                "extra_body": {"vendor_mode": "agent"},
            },
        ),
        reasoning_effort="xhigh",
    )
    if kind is AdapterKind.OPENAI_RESPONSES:
        adapter = OpenAIResponsesAdapter(provider=provider(), responses=client)
    elif kind is AdapterKind.MINIMAX:
        adapter = MiniMaxAdapter(provider=provider(), completions=client)
    else:
        adapter = OpenAIChatAdapter(provider=provider(), completions=client)
    await adapter.invoke(replace(request(spec), top_p=0.8, max_output_tokens=128))
    sent = client.calls[-1]
    assert sent["model"] == "vendor/version"
    if kind is AdapterKind.MINIMAX:
        assert "top_p" not in sent
    else:
        assert sent["top_p"] == 0.8
    extra = sent["extra_body"]
    assert isinstance(extra, dict)
    assert extra["vendor_mode"] == "agent"
    if kind is AdapterKind.MINIMAX:
        assert extra["reasoning_split"] is True
    assert not {"choices", "choice_rules"}.intersection(sent)
    if kind is not AdapterKind.OPENAI_RESPONSES:
        assert sent["reasoning_effort"] == "xhigh"
        assert sent["max_completion_tokens"] == 128
    else:
        assert sent["reasoning"] == {"effort": "xhigh"}
        assert sent["max_output_tokens"] == 128


@pytest.mark.parametrize(
    "field", ["model", "messages", "reasoning", "thinking", "top_p", "generationConfig"]
)
def test_extra_body_cannot_replace_owned_fields(field: str) -> None:
    with pytest.raises(ConfigError, match="framework-owned"):
        adapter_spec(AdapterKind.OPENAI_RESPONSES).validate_options(
            {"extra_body": {field: "value"}}, key="options"
        )


def test_four_modes_have_composed_rules_and_truthful_runtime_support() -> None:
    rules = adapter_specs_json()
    for kind in (AdapterKind.ANTHROPIC_MESSAGES, AdapterKind.GOOGLE_GENERATE_CONTENT):
        assert (
            next(item for item in rules if item["id"] == kind.value)[
                "runtime_available"
            ]
            is True
        )
    anthropic = adapter_spec(AdapterKind.ANTHROPIC_MESSAGES)
    anthropic.validate_options(
        {
            "thinking": "adaptive",
            "choices": {"reasoning_effort": ["high", "max"]},
            "thinking_display": "omitted",
            "prompt_cache_mode": "automatic",
            "prompt_cache_ttl": "1h",
        },
        key="options",
    )
    with pytest.raises(ConfigError, match="budget"):
        anthropic.validate_options({"thinking": "enabled"}, key="options")
    google = adapter_spec(AdapterKind.GOOGLE_GENERATE_CONTENT)
    google.validate_options(
        {
            "thinking_budget_tokens": -1,
            "include_thoughts": True,
            "prompt_cache_mode": "explicit",
            "prompt_cache_ttl": 600,
        },
        key="options",
    )
    with pytest.raises(ConfigError, match="effort or thinking budget"):
        google.validate_options(
            {"thinking_budget_tokens": 1024, "choices": {"reasoning_effort": ["high"]}},
            key="options",
            reasoning_effort="high",
        )
    with pytest.raises(ConfigError, match="requires"):
        google.validate_options(
            {"prompt_cache_mode": "implicit", "prompt_cache_ttl": 600}, key="options"
        )


@pytest.mark.parametrize(
    ("kind", "variant", "cache_ttl"),
    [
        (AdapterKind.OPENAI_CHAT, None, "30m"),
        (AdapterKind.OPENAI_RESPONSES, None, "30m"),
        (AdapterKind.GLM, None, None),
        (AdapterKind.KIMI, "k2", None),
        (AdapterKind.KIMI, "k3", "5m"),
        (AdapterKind.KIMI, "k3", "1h"),
    ],
)
async def test_installed_sdk_serializes_adapter_requests_without_network(
    kind: AdapterKind,
    variant: str | None,
    cache_ttl: str | None,
) -> None:
    captured: list[httpx.Request] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        captured.append(incoming)
        payload = {
            "id": "reply",
            "object": "chat.completion",
            "created": 0,
            "model": "vendor/version",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_tokens_details": {
                    "cached_tokens": 60,
                    "cache_write_tokens": 30,
                },
            },
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }
        if kind is AdapterKind.OPENAI_RESPONSES:
            payload = {
                "id": "reply",
                "object": "response",
                "created_at": 0,
                "model": "vendor/version",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs-1",
                        "summary": [],
                        "encrypted_content": "opaque",
                        "content": None,
                        "status": None,
                    }
                ],
                "status": "completed",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "input_tokens_details": {
                        "cached_tokens": 60,
                        "cache_write_tokens": 30,
                    },
                },
            }
        return httpx.Response(200, json=payload)

    async with AsyncOpenAI(
        api_key="test-key",
        base_url="https://example.test/v1",
        max_retries=0,
        default_headers={"X-Route": "test"},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as sdk:
        options: dict[str, object] = (
            {"prompt_cache_mode": "implicit", "prompt_cache_ttl": cache_ttl}
            if cache_ttl
            else {}
        )
        if kind is AdapterKind.KIMI:
            adapter = KimiAdapter(
                provider=replace(provider(), cache_key_header="x-session"),
                completions=cast(OpenAIChatCompletionsClient, sdk.chat.completions),
            )
            options["variant"] = variant
        elif kind is AdapterKind.GLM:
            adapter = GlmAdapter(
                provider=replace(provider(), cache_key_header="x-session"),
                completions=cast(OpenAIChatCompletionsClient, sdk.chat.completions),
            )
            options = {
                "thinking": "enabled",
                "do_sample": False,
                "user_id": "user-1",
            }
        elif kind is AdapterKind.OPENAI_CHAT:
            adapter = OpenAIChatAdapter(
                provider=replace(provider(), cache_key_header="x-session"),
                completions=cast(OpenAIChatCompletionsClient, sdk.chat.completions),
            )
        else:
            adapter = OpenAIResponsesAdapter(
                provider=replace(provider(), cache_key_header="x-session"),
                responses=cast(OpenAIResponsesClient, sdk.responses),
            )
            options["native_replay"] = "encrypted"
        spec = model(kind)
        spec = replace(
            spec,
            capabilities=spec.capabilities | {ModelCapability.PROMPT_CACHE},
            adapter_options=AdapterOptions(options),
        )
        outgoing = replace(
            request(spec),
            max_output_tokens=128,
            prompt_cache=PromptCache(
                key="2026-10-22/1",
                breakpoints=(PromptCacheBreakpoint("background", 0),),
            ),
        )
        first = await adapter.invoke(outgoing)
        assert first.usage.cached_input_tokens == 60
        assert first.usage.cache_creation_input_tokens == 30
        if kind is AdapterKind.OPENAI_RESPONSES:
            await adapter.invoke(
                replace(
                    outgoing,
                    messages=MessageStack.of(
                        AssistantMessage.from_text(
                            first.answer_text, reasoning=first.reasoning
                        ),
                        UserMessage.from_text("continue"),
                    ),
                )
            )
    assert len(captured) == (2 if kind is AdapterKind.OPENAI_RESPONSES else 1)
    if kind is AdapterKind.OPENAI_RESPONSES:
        replayed = json.loads(captured[1].content)["input"][0]
        assert replayed == {
            "type": "reasoning",
            "id": "rs-1",
            "summary": [],
            "encrypted_content": "opaque",
        }
    body = json.loads(captured[0].content)
    assert captured[0].headers["X-Route"] == "test"
    assert all(item.headers["x-session"] == "2026-10-22/1" for item in captured)
    assert body["model"] == "vendor/version"
    if kind is AdapterKind.GLM:
        assert body["do_sample"] is False
        assert body["thinking"] == {"type": "enabled", "clear_thinking": True}
        assert body["max_tokens"] == 128
        assert "prompt_cache_key" not in body
    else:
        assert body["prompt_cache_key"] == "2026-10-22/1"
        if cache_ttl:
            assert body["prompt_cache_options"] == {
                "mode": "implicit",
                "ttl": cache_ttl,
            }
        else:
            assert "prompt_cache_options" not in body
    if kind is AdapterKind.KIMI:
        assert "prompt_cache_breakpoint" not in captured[0].content.decode()


@pytest.mark.parametrize("change", ["none", "provider", "model", "content", "omit"])
async def test_native_responses_replay_preserves_order_and_requires_matching_source(
    change: str,
) -> None:
    output = [
        {
            "type": "reasoning",
            "id": "rs-1",
            "summary": [],
            "encrypted_content": "opaque",
        },
        {
            "type": "message",
            "id": "msg-1",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "working", "annotations": []}],
            "status": "completed",
        },
        {
            "type": "function_call",
            "name": "read",
            "call_id": "call-1",
            "arguments": "{}",
        },
    ]
    client = Client(SimpleNamespace(output=output, output_text="working"))
    spec = model(AdapterKind.OPENAI_RESPONSES, {"native_replay": "encrypted"})
    adapter = OpenAIResponsesAdapter(provider=provider(), responses=client)
    tools = ToolScope(
        tools=(
            ToolSpec(
                kind=ToolKind.ACTION,
                name="read",
                description="Read",
                parameters={"type": "object"},
            ),
        )
    )
    first = await adapter.invoke(
        replace(request(spec), tool_use=ToolUse.OPTIONAL, tool_scope=tools)
    )
    assert first.reasoning is not None
    message = AssistantMessage.from_text(
        "changed" if change == "content" else "working",
        reasoning=first.reasoning,
        tool_calls=first.tool_calls,
    )
    if change in {"provider", "model"}:
        binding = ModelProviderBinding(
            "other" if change == "provider" else "gateway",
            "other-model" if change == "model" else "vendor/version",
        )
        spec = replace(spec, providers=(binding,))
        adapter = OpenAIResponsesAdapter(
            provider=replace(provider(), id=binding.provider_id), responses=client
        )
    if change == "omit":
        spec = replace(spec, adapter_options=AdapterOptions())
    messages = MessageStack.of(
        message,
        ToolResultMessage.from_text(call_id="call-1", tool_name="read", text="result"),
    )
    await adapter.invoke(
        replace(request(spec, messages), tool_use=ToolUse.OPTIONAL, tool_scope=tools)
    )
    sent = client.calls[-1]["input"]
    assert isinstance(sent, list)
    if change == "none":
        assert sent[:3] == output
    else:
        assert all(item.get("type") != "reasoning" for item in sent)
    assert sent[-1]["type"] == "function_call_output"
