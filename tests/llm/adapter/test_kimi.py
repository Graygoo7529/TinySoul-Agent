from __future__ import annotations
from types import SimpleNamespace
import pytest
from tinysoul.llm.adapter import ProviderError, ProviderErrorKind
from tinysoul.llm.adapter.models.kimi import KimiAdapter
from tinysoul.llm.protocol.cache import PromptCache
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    MessageStack,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.protocol.responses import AnswerFormat
from tinysoul.llm.protocol.tools import (
    ToolCallRecord,
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


async def test_kimi_k2_7_adapter_maps_coding_plan_request_payload() -> None:
    message = SimpleNamespace(content='{"ok": true}', reasoning_content="thinking")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_tokens": 10, "completion_tokens": 3},
            id="chat_1",
            model="kimi-for-coding-highspeed",
        )
    )
    adapter = KimiAdapter(
        provider=_provider("kimi_coding"),
        completions=client,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="kimi_coding",
                provider_model="kimi-for-coding-highspeed",
                options={"thinking": "enabled"},
            ),
            messages=MessageStack.of(
                UserMessage.from_text("hello"),
                AssistantMessage.from_text(
                    '{"draft": true}',
                    reasoning="thinking trace",
                ),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            prompt_cache=PromptCache("kimi-prefix"),
            temperature=0.2,
            max_output_tokens=128,
            adapter_options={
                "thinking": "enabled",
                "native_replay": "content",
            },
        )
    )

    call = client.calls[0]
    assert call["model"] == "kimi-for-coding-highspeed"
    assert "temperature" not in call
    assert call["messages"] == [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": '{"draft": true}',
            "reasoning_content": "thinking trace",
        },
    ]
    assert call["max_completion_tokens"] == 128
    assert "max_output_tokens" not in call
    assert call["response_format"] == {"type": "json_object"}
    assert call["prompt_cache_key"] == "kimi-prefix"
    assert call["extra_body"] == {"thinking": {"type": "enabled", "keep": "all"}}
    assert response.answer_text == '{"ok": true}'
    assert response.reasoning is not None
    assert response.reasoning.summary == "thinking"
    assert response.reasoning.summary == "thinking"


async def test_kimi_k3_adapter_maps_reasoning_without_k2_thinking() -> None:
    message = SimpleNamespace(content='{"ok": true}', reasoning_content="thinking")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_tokens": 10, "completion_tokens": 3},
            id="chat_k3_1",
            model="k3",
        )
    )
    adapter = KimiAdapter(
        provider=_provider("kimi_coding"),
        completions=client,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="kimi_coding",
                provider_model="k3",
                options={
                    "variant": "k3",
                    "choices": {"reasoning_effort": ["max"]},
                },
                reasoning_effort="max",
            ),
            messages=MessageStack.of(
                UserMessage.from_text("hello"),
                AssistantMessage.from_text(
                    '{"draft": true}',
                    reasoning="thinking trace",
                ),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            prompt_cache=PromptCache("kimi-k3-prefix"),
            temperature=0.2,
            max_output_tokens=128,
            adapter_options={
                "variant": "k3",
                "choices": {"reasoning_effort": ["max"]},
            },
            reasoning_effort="max",
        )
    )

    call = client.calls[0]
    assert call["model"] == "k3"
    assert "temperature" not in call
    assert call["reasoning_effort"] == "max"
    assert call["messages"] == [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": '{"draft": true}',
            "reasoning_content": "thinking trace",
        },
    ]
    assert call["max_completion_tokens"] == 128
    assert call["response_format"] == {"type": "json_object"}
    assert call["prompt_cache_key"] == "kimi-k3-prefix"
    assert "extra_body" not in call
    assert response.answer_text == '{"ok": true}'
    assert response.reasoning is not None
    assert response.reasoning.summary == "thinking"


async def test_kimi_k3_adapter_rejects_k2_thinking_option() -> None:
    adapter = KimiAdapter(
        provider=_provider("kimi_coding"),
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(
                        provider_id="kimi_coding",
                        provider_model="k3",
                        options={"variant": "k3"},
                    ),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.TEXT,
                    adapter_options={"variant": "k3", "thinking": "enabled"},
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


async def test_kimi_k3_adapter_replays_reasoning_with_tool_calls_and_results() -> None:
    message = SimpleNamespace(content="ok", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiAdapter(
        provider=_provider("kimi_coding"),
        completions=client,
    )
    tool_call = ToolCallRecord(
        id="provider_call_1",
        name="workspace.list",
        arguments={"path": "workspace:doc.md"},
    )
    tool = ToolSpec(
        name="workspace.list",
        description="Scan the workspace",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(
                    provider_id="kimi_coding",
                    provider_model="k3",
                    options={"variant": "k3"},
                ),
                messages=MessageStack.of(
                    AssistantMessage.from_parts(
                        reasoning="tool reasoning",
                        tool_calls=(tool_call,),
                    ),
                    ToolResultMessage.from_json(
                        call_id="provider_call_1",
                        tool_name="workspace.list",
                        value={"ok": True},
                    ),
                ),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(tools=(tool,)),
                tool_use=ToolUse.OPTIONAL,
                adapter_options={
                    "variant": "k3",
                    "choices": {"reasoning_effort": ["max"]},
                },
                reasoning_effort="max",
            )
        )
    )

    assert client.calls[0]["messages"] == [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "tool reasoning",
            "tool_calls": [
                {
                    "id": "provider_call_1",
                    "type": "function",
                    "function": {
                        "name": "workspace_list",
                        "arguments": '{"path":"workspace:doc.md"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "provider_call_1",
            "content": '```json\n{"ok":true}\n```',
            "name": "workspace_list",
        },
    ]
    assert client.calls[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "workspace_list",
                "description": "Scan the workspace",
                "parameters": {"type": "object"},
            },
        }
    ]
    assert client.calls[0]["reasoning_effort"] == "max"


async def test_kimi_adapter_preserves_pending_call_without_native_reasoning() -> None:
    message = SimpleNamespace(
        content='{"text":"\u4f60\u597d"}',
        reasoning_content="answer reasoning",
        tool_calls=[],
    )
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiAdapter(
        provider=_provider("kimi_coding"),
        completions=client,
    )
    unresolved_call = ToolCallRecord(
        id="tool_5EPQk3dnZPdE13NVvWmuVd1S",
        name="core.answer",
        arguments={"guide_blocks": [{"text": "Answer the user."}]},
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(
                    provider_id="kimi_coding",
                    provider_model="kimi-for-coding-highspeed",
                ),
                messages=MessageStack.of(
                    AssistantMessage.from_parts(
                        reasoning="decision reasoning",
                        tool_calls=(unresolved_call,),
                    ),
                    UserMessage.from_text("Return the final answer as JSON."),
                ),
                answer_format=AnswerFormat.JSON_OBJECT,
                tool_use=ToolUse.DISABLED,
                adapter_options={
                    "thinking": "enabled",
                    "native_replay": "content",
                },
            )
        )
    )

    items = _message_payloads(client.calls[0]["messages"])
    assert [item["role"] for item in items] == ["assistant", "user"]
    assert unresolved_call.id in str(items[0])
    assert "Answer the user." in str(items[0])
    assert "decision reasoning" not in str(items)
    assert all(
        "tool_calls" not in item and "reasoning_content" not in item for item in items
    )
    assert "tools" not in client.calls[0]


async def test_kimi_adapter_renders_tool_result_as_disabled_context() -> None:
    message = SimpleNamespace(
        content='{"text":"\u4f60\u597d"}',
        reasoning_content="answer reasoning",
        tool_calls=[],
    )
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiAdapter(
        provider=_provider("kimi_coding"),
        completions=client,
    )
    completed_call = ToolCallRecord(
        id="tool_5EPQk3dnZPdE13NVvWmuVd1S",
        name="core.answer",
        arguments={"guide_blocks": [{"text": "Answer the user."}]},
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(
                    provider_id="kimi_coding",
                    provider_model="kimi-for-coding-highspeed",
                ),
                messages=MessageStack.of(
                    AssistantMessage.from_tool_calls(completed_call),
                    ToolResultMessage.from_json(
                        call_id=completed_call.id,
                        tool_name=completed_call.name,
                        value={"ok": True},
                    ),
                    UserMessage.from_text("Return the final answer as JSON."),
                ),
                answer_format=AnswerFormat.JSON_OBJECT,
                tool_use=ToolUse.DISABLED,
                adapter_options={"thinking": "enabled"},
            )
        )
    )

    items = _message_payloads(client.calls[0]["messages"])
    assert [item["role"] for item in items] == ["assistant", "user", "user"]
    assert all(completed_call.id in str(item) for item in items[:2])
    assert completed_call.name in str(items[1])
    assert '{"ok":true}' in str(items[1])
    assert "Return the final answer as JSON." in str(items[2])
    assert "tools" not in client.calls[0]


@pytest.mark.parametrize(
    ("provider_model", "expected_tool_choice"),
    (("kimi-for-coding-highspeed", "auto"), ("k3", "required")),
)
async def test_kimi_adapter_maps_model_specific_required_tool_choice(
    provider_model: str,
    expected_tool_choice: str,
) -> None:
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
    adapter = KimiAdapter(
        provider=_provider("kimi_coding"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(
                    provider_id="kimi_coding",
                    provider_model=provider_model,
                    options=(
                        {"variant": "k3"}
                        if provider_model == "k3"
                        else {"variant": "k2"}
                    ),
                ),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(tools=(_tool(),)),
                tool_use=ToolUse.REQUIRED,
            )
        )
    )

    assert client.calls[0]["tool_choice"] == expected_tool_choice


async def test_kimi_adapter_keeps_all_visible_tools_for_forced_tool_choice() -> None:
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
    adapter = KimiAdapter(
        provider=_provider("kimi"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(
                    tools=(_tool(), write_tool),
                    selection=ToolSelection(forced_name="read_file"),
                ),
                tool_use=ToolUse.REQUIRED,
            )
        )
    )

    assert client.calls[0]["tool_choice"] == "auto"
    assert client.calls[0]["tools"] == [
        _provider_tool_payload(),
        _write_provider_tool_payload(),
    ]


async def test_kimi_adapter_skips_message_reasoning_without_native_replay() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = KimiAdapter(
        provider=_provider("kimi"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
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
    assert client.calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}


async def test_kimi_adapter_rejects_partial_provider_option() -> None:
    adapter = KimiAdapter(
        provider=_provider("kimi"),
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.TEXT,
                    adapter_options={"partial": True},
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


async def test_kimi_adapter_maps_dotted_tool_name_and_decodes_response() -> None:
    message = SimpleNamespace(
        content="",
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                type="function",
                function=SimpleNamespace(name="core_answer", arguments="{}"),
            )
        ],
    )
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiAdapter(
        provider=_provider("kimi"),
        completions=client,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
            messages=MessageStack.of(UserMessage.from_text("answer")),
            answer_format=AnswerFormat.NONE,
            tool_scope=ToolScope(
                tools=(
                    ToolSpec(
                        name="core.answer",
                        description="Answer the user",
                        parameters={"type": "object"},
                        kind=ToolKind.ACTION,
                    ),
                ),
            ),
            tool_use=ToolUse.REQUIRED,
        )
    )

    assert client.calls[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "core_answer",
                "description": "Answer the user",
                "parameters": {"type": "object"},
            },
        }
    ]
    assert response.tool_calls[0].name == "core.answer"


async def test_kimi_adapter_rejects_more_than_128_visible_tools() -> None:
    adapter = KimiAdapter(
        provider=_provider("kimi"),
        completions=FakeCreateClient(response=object()),
    )
    tools = tuple(
        ToolSpec(
            name=f"tool_{index}",
            description="Tool",
            parameters={"type": "object"},
            kind=ToolKind.ACTION,
        )
        for index in range(129)
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.NONE,
                    tool_scope=ToolScope(tools=tools),
                    tool_use=ToolUse.OPTIONAL,
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


async def test_kimi_adapter_validates_only_visible_tools() -> None:
    message = SimpleNamespace(content="ok", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiAdapter(
        provider=_provider("kimi"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(
                    tools=(
                        _tool(),
                        ToolSpec(
                            name="1bad",
                            description="bad",
                            parameters={"type": "object"},
                            kind=ToolKind.ACTION,
                        ),
                    ),
                    selection=ToolSelection(("read_file",)),
                ),
                tool_use=ToolUse.OPTIONAL,
            )
        )
    )

    assert client.calls[0]["tools"] == [_provider_tool_payload()]
