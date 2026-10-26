from __future__ import annotations
from types import SimpleNamespace
import pytest
from tinysoul.llm.adapter import ProviderError, ProviderErrorKind
from tinysoul.llm.adapter.models.glm import GlmAdapter
from tinysoul.llm.adapter.models.minimax import MiniMaxAdapter
from tinysoul.llm.config.loader import AdapterKind
from tinysoul.llm.protocol.messages import AssistantMessage, MessageStack, UserMessage
from tinysoul.llm.protocol.models import (
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
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
    _message_payloads,
    _model,
    _provider,
    _provider_tool_payload,
    _tool,
    _write_provider_tool_payload,
)


async def test_glm_adapter_maps_required_tool_choice_to_auto() -> None:
    write_tool = ToolSpec(
        name="write_file",
        description="Write a workspace file",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        kind=ToolKind.ACTION,
    )
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
    adapter = GlmAdapter(
        provider=_provider("glm"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="glm", provider_model="glm-5.1"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(
                    tools=(_tool(), write_tool),
                    selection=ToolSelection(forced_name="read_file"),
                ),
                tool_use=ToolUse.REQUIRED,
                adapter_options={"thinking": "enabled", "native_replay": "content"},
            )
        )
    )

    assert client.calls[0]["tool_choice"] == "auto"
    assert client.calls[0]["tools"] == [
        _provider_tool_payload(),
        _write_provider_tool_payload(),
    ]


async def test_glm_adapter_rejects_strict_tool_calling() -> None:
    strict_tool = ToolSpec(
        name="read_file",
        description="Read a workspace file",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
        strict=True,
    )
    adapter = GlmAdapter(
        provider=_provider("glm"),
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(provider_id="glm", provider_model="glm-5.1"),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.TEXT,
                    tool_scope=ToolScope(tools=(strict_tool,)),
                    tool_use=ToolUse.REQUIRED,
                    adapter_options={"thinking": "enabled"},
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


async def test_glm_adapter_maps_thinking_and_max_tokens() -> None:
    message = SimpleNamespace(content='{"ok": true}', reasoning_content="reasoning")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_tokens": 10, "completion_tokens": 4},
            id="chat_3",
            model="glm-5.1",
        )
    )
    adapter = GlmAdapter(
        provider=_provider("glm"),
        completions=client,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="glm",
                provider_model="glm-5.1",
                options={"thinking": "enabled"},
            ),
            messages=MessageStack.of(
                UserMessage.from_text("json please"),
                AssistantMessage.from_text(
                    '{"plan": "call action"}',
                    reasoning="reasoning trace",
                ),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            max_output_tokens=128,
            adapter_options={"thinking": "enabled", "native_replay": "content"},
        )
    )

    call = client.calls[0]
    assert call["model"] == "glm-5.1"
    messages = _message_payloads(call["messages"])
    assert messages[1]["reasoning_content"] == "reasoning trace"
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {
        "thinking": {"type": "enabled", "clear_thinking": False}
    }
    assert call["max_tokens"] == 128
    assert "max_completion_tokens" not in call
    assert response.reasoning is not None
    assert response.reasoning.summary == "reasoning"
    assert response.reasoning.summary == "reasoning"
    assert response.usage.input_tokens == 10 and response.usage.output_tokens == 4


async def test_glm_adapter_skips_message_reasoning_without_native_replay() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = GlmAdapter(
        provider=_provider("glm"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="glm", provider_model="glm-5.1"),
                messages=MessageStack.of(
                    AssistantMessage.from_text(
                        "previous answer",
                        reasoning="thinking trace",
                    )
                ),
                answer_format=AnswerFormat.TEXT,
                adapter_options={"thinking": "enabled"},
            )
        )
    )

    assert client.calls[0]["messages"] == [
        {"role": "assistant", "content": "previous answer"}
    ]
    assert client.calls[0]["extra_body"] == {
        "thinking": {"type": "enabled", "clear_thinking": True}
    }


async def test_glm_adapter_maps_reasoning_effort_provider_option() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = GlmAdapter(
        provider=_provider("glm"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="glm", provider_model="glm-5.2"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                adapter_options={"choices": {"reasoning_effort": ["max"]}},
                reasoning_effort="max",
            )
        )
    )

    assert client.calls[0]["reasoning_effort"] == "max"


async def test_minimax_adapter_maps_thinking_and_reasoning_split() -> None:
    message = SimpleNamespace(
        content='{"ok": true}',
        reasoning_content="reasoning",
    )
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_tokens": 10, "completion_tokens": 4},
            id="chat_4",
            model="MiniMax-M3",
        )
    )
    adapter = MiniMaxAdapter(
        provider=_provider("minimax"),
        completions=client,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=ModelSpec(
                id="minimax-latest",
                providers=(ModelProviderBinding("minimax", "MiniMax-M3"),),
                context_window_tokens=262_144,
                adapter=AdapterKind.MINIMAX,
                capabilities=frozenset(
                    {
                        ModelCapability.TEXT_INPUT,
                        ModelCapability.IMAGE_INPUT,
                        ModelCapability.IMAGE_REMOTE_URL,
                        ModelCapability.REASONING_OUTPUT,
                    }
                ),
            ),
            messages=MessageStack.of(
                UserMessage.from_text("json please"),
                AssistantMessage.from_text(
                    '{"plan": "continue"}',
                    reasoning="reasoning trace",
                ),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            max_output_tokens=128,
            adapter_options={
                "thinking": "adaptive",
                "reasoning_split": True,
                "native_replay": "content",
            },
        )
    )

    call = client.calls[0]
    assert call["model"] == "MiniMax-M3"
    messages = _message_payloads(call["messages"])
    assert messages[1]["reasoning_content"] == "reasoning trace"
    assert call["max_completion_tokens"] == 128
    assert "response_format" not in call
    assert call["extra_body"] == {
        "thinking": {"type": "adaptive"},
        "reasoning_split": True,
    }
    assert response.answer_text == '{"ok": true}'
    assert response.reasoning is not None
    assert response.reasoning.summary == "reasoning"
    assert response.reasoning.summary == "reasoning"


async def test_minimax_adapter_removes_required_tool_choice() -> None:
    write_tool = ToolSpec(
        name="write_file",
        description="Write a workspace file",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        kind=ToolKind.ACTION,
    )
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
    adapter = MiniMaxAdapter(
        provider=_provider("minimax"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="minimax", provider_model="MiniMax-M3"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(
                    tools=(_tool(), write_tool),
                    selection=ToolSelection(forced_name="read_file"),
                ),
                tool_use=ToolUse.REQUIRED,
                adapter_options={
                    "thinking": "adaptive",
                    "reasoning_split": True,
                    "native_replay": "content",
                },
            )
        )
    )

    assert "tool_choice" not in client.calls[0]
    assert client.calls[0]["tools"] == [
        _provider_tool_payload(),
        _write_provider_tool_payload(),
    ]


async def test_minimax_adapter_rejects_strict_tool_calling() -> None:
    strict_tool = ToolSpec(
        name="read_file",
        description="Read a workspace file",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
        strict=True,
    )
    adapter = MiniMaxAdapter(
        provider=_provider("minimax"),
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(provider_id="minimax", provider_model="MiniMax-M3"),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.TEXT,
                    tool_scope=ToolScope(tools=(strict_tool,)),
                    tool_use=ToolUse.REQUIRED,
                    adapter_options={"thinking": "adaptive"},
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG
