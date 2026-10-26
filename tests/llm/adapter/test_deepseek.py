from __future__ import annotations
from dataclasses import replace
from types import SimpleNamespace
import pytest
from tinysoul.llm.adapter import ProviderError, ProviderErrorKind, ProviderFailureScope
from tinysoul.llm.adapter.models.deepseek import DeepSeekAdapter
from tinysoul.llm.config.loader import ApiMode, ProviderEndpoint
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    ImagePart,
    ImageUrlPart,
    MessageStack,
    SystemMessage,
    TextPart,
    UserMessage,
)
from tinysoul.llm.protocol.responses import AnswerFormat
from tinysoul.llm.protocol.tools import (
    ToolKind,
    ToolScope,
    ToolSelection,
    ToolSpec,
    ToolUse,
)
from tests.llm.adapter.support import (
    FakeCreateClient,
    ProviderRequest,
    _mapping_payload,
    _message_payloads,
    _model,
    _provider,
    _provider_tool_payload,
    _tool,
)


async def test_deepseek_adapter_maps_thinking_and_reasoning_effort() -> None:
    message = SimpleNamespace(content='{"ok": true}', reasoning_content="reasoning")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_cache_hit_tokens": 8, "prompt_cache_miss_tokens": 2},
            id="chat_2",
            model="deepseek-v4-pro",
        )
    )
    adapter = DeepSeekAdapter(
        provider=_provider("deepseek"),
        completions=client,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="deepseek",
                provider_model="deepseek-v4-pro",
                options={
                    "thinking": "enabled",
                    "choices": {"reasoning_effort": ["low"]},
                },
                reasoning_effort="low",
            ),
            messages=MessageStack.of(
                UserMessage.from_text("json please"),
                AssistantMessage.from_text(
                    '{"plan": "call action"}',
                    reasoning="reasoning trace",
                ),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            temperature=0.7,
            max_output_tokens=128,
            adapter_options={
                "thinking": "enabled",
                "choices": {"reasoning_effort": ["low"]},
                "native_replay": "content",
            },
            reasoning_effort="low",
        )
    )

    call = client.calls[0]
    assert call["model"] == "deepseek-v4-pro"
    messages = _message_payloads(call["messages"])
    assert messages[1]["reasoning_content"] == "reasoning trace"
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {"thinking": {"type": "enabled"}}
    assert call["reasoning_effort"] == "low"
    assert call["max_tokens"] == 128
    assert "max_completion_tokens" not in call
    assert "temperature" not in call
    assert "prompt_cache_key" not in call
    assert response.reasoning is not None
    assert response.reasoning.summary == "reasoning"
    assert response.reasoning.summary == "reasoning"
    assert response.usage.cached_input_tokens == 8


async def test_deepseek_adapter_maps_user_images() -> None:
    message = SimpleNamespace(content="ok", reasoning_content=None)
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = DeepSeekAdapter(
        provider=_provider("deepseek"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(
                    provider_id="deepseek",
                    provider_model="deepseek-flash",
                ),
                messages=MessageStack.of(
                    UserMessage.from_parts(
                        TextPart("Describe the images."),
                        ImagePart(data=b"abc", mime_type="image/png"),
                        ImageUrlPart(url="https://example.test/image.png"),
                    )
                ),
                answer_format=AnswerFormat.TEXT,
            )
        )
    )

    assert client.calls[0]["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe the images."},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,YWJj"},
                },
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.test/image.png"},
                },
            ],
        }
    ]


@pytest.mark.parametrize(
    "message",
    (
        SystemMessage.from_parts(ImagePart(data=b"abc", mime_type="image/png")),
        AssistantMessage.from_parts(ImageUrlPart(url="https://example.test/image.png")),
    ),
)
async def test_deepseek_adapter_rejects_images_outside_user_messages(
    message: SystemMessage | AssistantMessage,
) -> None:
    client = FakeCreateClient(response=object())
    adapter = DeepSeekAdapter(
        provider=_provider("deepseek"),
        completions=client,
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(
                        provider_id="deepseek",
                        provider_model="deepseek-flash",
                    ),
                    messages=MessageStack.of(message),
                    answer_format=AnswerFormat.TEXT,
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CAPABILITY
    assert exc.value.scope is ProviderFailureScope.MODEL
    assert client.calls == []


async def test_deepseek_adapter_uses_default_thinking_without_reasoning_replay() -> (
    None
):
    message = SimpleNamespace(content="ok", reasoning_content="reasoning")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = DeepSeekAdapter(
        provider=_provider("deepseek"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="deepseek", provider_model="deepseek-v4-pro"),
                messages=MessageStack.of(
                    AssistantMessage.from_text(
                        "previous answer",
                        reasoning="reasoning trace",
                    )
                ),
                answer_format=AnswerFormat.TEXT,
                temperature=0.7,
            )
        )
    )

    assert client.calls[0]["messages"] == [
        {"role": "assistant", "content": "previous answer"}
    ]
    assert "temperature" not in client.calls[0]
    assert "extra_body" not in client.calls[0]


async def test_deepseek_adapter_omits_tool_choice_with_thinking() -> None:
    message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="provider_call_1",
                type="function",
                function=SimpleNamespace(name="read_file", arguments="{}"),
            )
        ],
    )
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = DeepSeekAdapter(
        provider=_provider("deepseek"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="deepseek", provider_model="deepseek-v4-pro"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(tools=(_tool(),)),
                tool_use=ToolUse.REQUIRED,
                adapter_options={
                    "thinking": "enabled",
                    "choices": {"reasoning_effort": ["high"]},
                    "native_replay": "content",
                },
                reasoning_effort="high",
            )
        )
    )

    assert "tool_choice" not in client.calls[0]


async def test_deepseek_adapter_requires_reasoning_replay_with_thinking_tools() -> None:
    client = FakeCreateClient(response=object())
    adapter = DeepSeekAdapter(
        provider=_provider("deepseek"),
        completions=client,
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(
                        provider_id="deepseek",
                        provider_model="deepseek-v4-pro",
                    ),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.TEXT,
                    tool_scope=ToolScope(tools=(_tool(),)),
                    tool_use=ToolUse.OPTIONAL,
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG
    assert exc.value.scope is ProviderFailureScope.MODEL
    assert client.calls == []


async def test_deepseek_adapter_maps_resource_interruption_to_transient_error() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="partial"),
                    finish_reason="insufficient_system_resource",
                )
            ],
            usage={},
        )
    )
    adapter = DeepSeekAdapter(
        provider=_provider("deepseek"),
        completions=client,
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(
                        provider_id="deepseek",
                        provider_model="deepseek-flash",
                    ),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.TEXT,
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.TRANSIENT
    assert exc.value.scope is ProviderFailureScope.PROVIDER


async def test_deepseek_adapter_rejects_strict_tools() -> None:
    adapter = DeepSeekAdapter(
        provider=_provider("deepseek"),
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(
                        provider_id="deepseek",
                        provider_model="deepseek-v4-pro",
                    ),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.TEXT,
                    tool_scope=ToolScope(
                        tools=(
                            ToolSpec(
                                name="read_file",
                                description="Read",
                                parameters={"type": "object"},
                                kind=ToolKind.ACTION,
                                strict=True,
                            ),
                        ),
                    ),
                    tool_use=ToolUse.OPTIONAL,
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


async def test_deepseek_beta_endpoint_maps_strict_tools() -> None:
    message = SimpleNamespace(content="ok", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    beta_provider = replace(
        _provider("deepseek"),
        endpoints=(
            ProviderEndpoint(ApiMode.OPENAI_CHAT, "https://api.deepseek.com/beta"),
        ),
    )
    adapter = DeepSeekAdapter(provider=beta_provider, completions=client)

    await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="deepseek",
                provider_model="deepseek-v4-pro",
                options={"native_replay": "content"},
            ),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
            tool_scope=ToolScope(
                tools=(
                    ToolSpec(
                        name="read_file",
                        description="Read",
                        parameters={"type": "object"},
                        kind=ToolKind.ACTION,
                        strict=True,
                    ),
                ),
            ),
            tool_use=ToolUse.OPTIONAL,
        )
    )

    assert (
        _mapping_payload(_message_payloads(client.calls[0]["tools"])[0]["function"])[
            "strict"
        ]
        is True
    )


async def test_deepseek_adapter_validates_only_visible_tools() -> None:
    message = SimpleNamespace(content="ok", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = DeepSeekAdapter(
        provider=_provider("deepseek"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(
                    provider_id="deepseek",
                    provider_model="deepseek-v4-pro",
                ),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(
                    tools=(
                        _tool(),
                        ToolSpec(
                            name="strict_hidden",
                            description="Hidden strict tool",
                            parameters={"type": "object"},
                            kind=ToolKind.ACTION,
                            strict=True,
                        ),
                    ),
                    selection=ToolSelection(("read_file",)),
                ),
                tool_use=ToolUse.OPTIONAL,
                adapter_options={"native_replay": "content"},
            )
        )
    )

    assert client.calls[0]["tools"] == [_provider_tool_payload()]


async def test_deepseek_adapter_rejects_more_than_128_tools() -> None:
    client = FakeCreateClient(response=object())
    adapter = DeepSeekAdapter(
        provider=_provider("deepseek"),
        completions=client,
    )
    tools = tuple(
        ToolSpec(
            name=f"tool_{index}",
            description="Read",
            parameters={"type": "object"},
            kind=ToolKind.ACTION,
        )
        for index in range(129)
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(
                        provider_id="deepseek",
                        provider_model="deepseek-v4-pro",
                    ),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.TEXT,
                    tool_scope=ToolScope(tools=tools),
                    tool_use=ToolUse.OPTIONAL,
                    adapter_options={"native_replay": "content"},
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG
    assert client.calls == []
