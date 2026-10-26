from __future__ import annotations
from types import SimpleNamespace
import pytest
from tinysoul.infra.json import JsonObject
from tinysoul.llm.adapter import ProviderError, ProviderErrorKind
from tinysoul.llm.adapter.models.gpt import GptAdapter
from tinysoul.llm.protocol.cache import PromptCache, PromptCacheBreakpoint
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    ImagePart,
    JsonPart,
    MessageStack,
    SystemMessage,
    TextPart,
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
    _responses_tool_payload,
    _tool,
)


async def test_openai_responses_adapter_maps_request_payload() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text='{"ok": true}',
            output=[],
            usage={"input_tokens": 10, "output_tokens": 3},
            id="resp_1",
            model="gpt-5.5",
            status="completed",
        )
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="openai",
                provider_model="gpt-5.5",
                options={
                    "prompt_cache_mode": "implicit",
                    "prompt_cache_ttl": "30m",
                    "choices": {"reasoning_effort": ["high"]},
                    "reasoning_summary": "auto",
                    "native_replay": "encrypted",
                    "verbosity": "medium",
                },
                reasoning_effort="high",
                top_p=0.8,
            ),
            messages=MessageStack.of(
                SystemMessage.from_text("system"),
                UserMessage.from_parts(
                    TextPart("look"),
                    ImagePart(data=b"abc", mime_type="image/png"),
                ),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            prompt_cache=PromptCache("stable-prefix"),
            temperature=0.2,
            max_output_tokens=256,
            adapter_options={
                "prompt_cache_mode": "implicit",
                "prompt_cache_ttl": "30m",
                "choices": {"reasoning_effort": ["high"]},
                "reasoning_summary": "auto",
                "native_replay": "encrypted",
                "verbosity": "medium",
            },
            reasoning_effort="high",
            top_p=0.8,
        )
    )

    call = client.calls[0]
    assert call["model"] == "gpt-5.5"
    assert "temperature" not in call
    assert "top_p" not in call
    assert call["max_output_tokens"] == 256
    assert call["prompt_cache_key"] == "stable-prefix"
    assert call["prompt_cache_options"] == {"mode": "implicit", "ttl": "30m"}
    assert call["reasoning"] == {"effort": "high", "summary": "auto"}
    assert call["include"] == ["reasoning.encrypted_content"]
    assert call["text"] == {
        "format": {"type": "json_object"},
        "verbosity": "medium",
    }
    assert "reasoning_effort" not in call
    assert response.answer_text == '{"ok": true}'
    assert response.usage.input_tokens == 10 and response.usage.output_tokens == 3


async def test_openai_responses_adapter_keeps_sampling_without_active_reasoning() -> (
    None
):
    client = FakeCreateClient(
        response=SimpleNamespace(output_text="ok", output=[], usage={})
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                temperature=1.0,
                max_output_tokens=128,
                adapter_options={"choices": {"reasoning_effort": ["none"]}},
                reasoning_effort="none",
                top_p=0.8,
            )
        )
    )

    call = client.calls[0]
    assert call["temperature"] == pytest.approx(1.0)
    assert call["top_p"] == pytest.approx(0.8)
    assert call["reasoning"] == {"effort": "none"}
    assert call["max_output_tokens"] == 128


async def test_openai_responses_adapter_extracts_reasoning_content() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="done",
            output=[
                SimpleNamespace(
                    type="reasoning",
                    summary=[SimpleNamespace(text="summary")],
                    content=[SimpleNamespace(text="detail")],
                )
            ],
            usage={},
        )
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="openai",
                provider_model="gpt-5.5",
                options={"native_replay": "encrypted"},
            ),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
        )
    )

    assert response.reasoning is not None
    assert response.reasoning.summary == "summary\ndetail"


async def test_openai_responses_adapter_extracts_encrypted_reasoning_items() -> None:
    provider_item: JsonObject = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "summary"}],
        "content": [],
        "encrypted_content": "encrypted-state",
        "status": None,
    }
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="done",
            output=[provider_item],
            usage={},
        )
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="openai",
                provider_model="gpt-5.5",
                options={"native_replay": "encrypted"},
            ),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
        )
    )

    assert response.reasoning is not None
    assert response.reasoning.summary == "summary"
    assert response.reasoning.native_items == (
        {key: value for key, value in provider_item.items() if key != "status"},
    )


async def test_openai_responses_adapter_rejects_text_native_replay() -> None:
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(provider_id="openai", provider_model="gpt-5.5"),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.TEXT,
                    adapter_options={"native_replay": "content"},
                )
            )
        )
    assert exc.value.kind is ProviderErrorKind.CONFIG


async def test_openai_responses_keeps_encrypted_replay_without_summary() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="done",
            output=[
                {
                    "type": "reasoning",
                    "summary": [],
                    "content": [],
                    "encrypted_content": "opaque-state",
                }
            ],
            usage={},
        )
    )
    adapter = GptAdapter(provider=_provider("openai"), responses=client)

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="openai",
                provider_model="gpt-5.5",
                options={"native_replay": "encrypted"},
            ),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
        )
    )

    assert response.reasoning is not None
    assert response.reasoning.summary is None
    assert response.reasoning.native_replay is not None


async def test_openai_responses_adapter_maps_text_and_json_as_input_text() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="ok",
            output=[],
            usage={},
        )
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(
                    UserMessage.from_parts(
                        TextPart("工具返回如下："),
                        JsonPart({"source": "tool_result", "ok": True}),
                    )
                ),
                answer_format=AnswerFormat.TEXT,
            )
        )
    )

    assert client.calls[0]["input"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "工具返回如下：\n\n```json\n"
                        '{"ok":true,"source":"tool_result"}\n```'
                    ),
                }
            ],
        }
    ]


async def test_openai_responses_adapter_maps_tools_and_tool_results() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="provider_call_2",
                    name="read_file",
                    arguments='{"path":"workspace:next.md"}',
                )
            ],
            usage={},
        )
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )
    tool_call = ToolCallRecord(
        id="provider_call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(
                AssistantMessage.from_tool_calls(tool_call),
                ToolResultMessage.from_json(
                    call_id="provider_call_1",
                    tool_name="read_file",
                    value={"ok": True},
                ),
            ),
            answer_format=AnswerFormat.NONE,
            tool_scope=ToolScope(tools=(_tool(),)),
            tool_use=ToolUse.REQUIRED,
        )
    )

    call = client.calls[0]
    assert call["tools"] == [_responses_tool_payload()]
    assert call["input"] == [
        {
            "type": "function_call",
            "call_id": "provider_call_1",
            "name": "read_file",
            "arguments": '{"path":"workspace:doc.md"}',
        },
        {
            "type": "function_call_output",
            "call_id": "provider_call_1",
            "output": '```json\n{"ok":true}\n```',
        },
    ]
    assert response.tool_calls[0].id == "provider_call_2"
    assert response.tool_calls[0].arguments == {"path": "workspace:next.md"}


async def test_openai_responses_adapter_maps_dotted_tool_names_round_trip() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="provider_call_1",
                    name="workspace_list",
                    arguments="{}",
                )
            ],
            usage={},
        )
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )
    tool = ToolSpec(
        name="workspace.list",
        description="Scan the workspace",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(UserMessage.from_text("scan")),
            answer_format=AnswerFormat.NONE,
            tool_scope=ToolScope(tools=(tool,)),
            tool_use=ToolUse.REQUIRED,
        )
    )

    assert client.calls[0]["tools"] == [
        {
            "type": "function",
            "name": "workspace_list",
            "description": "Scan the workspace",
            "parameters": {"type": "object"},
        }
    ]
    assert response.tool_calls[0].name == "workspace.list"


async def test_openai_responses_adapter_preserves_pending_call_as_context() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(output_text='{"text":"hello"}', output=[], usage={})
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )
    unresolved_call = ToolCallRecord(
        id="call_unresolved",
        name="core.answer",
        arguments={},
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(
                    AssistantMessage.from_tool_calls(unresolved_call),
                    UserMessage.from_text("Return the final answer as JSON."),
                ),
                answer_format=AnswerFormat.JSON_OBJECT,
                tool_use=ToolUse.DISABLED,
            )
        )
    )

    items = _message_payloads(client.calls[0]["input"])
    assert [item["role"] for item in items] == ["assistant", "user"]
    assert unresolved_call.id in str(items[0])
    assert unresolved_call.name in str(items[0])
    assert "Return the final answer as JSON." in str(items[1])
    assert "tools" not in client.calls[0]


async def test_openai_responses_adapter_renders_tool_result_as_disabled_context() -> (
    None
):
    client = FakeCreateClient(
        response=SimpleNamespace(output_text='{"text":"hello"}', output=[], usage={})
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )
    completed_call = ToolCallRecord(
        id="call_completed",
        name="core.answer",
        arguments={},
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(
                    AssistantMessage.from_tool_calls(completed_call),
                    ToolResultMessage.from_json(
                        call_id="call_completed",
                        tool_name="core.answer",
                        value={"ok": True},
                    ),
                    UserMessage.from_text("Return the final answer as JSON."),
                ),
                answer_format=AnswerFormat.JSON_OBJECT,
                tool_use=ToolUse.DISABLED,
            )
        )
    )

    items = _message_payloads(client.calls[0]["input"])
    assert [item["role"] for item in items] == ["assistant", "user", "user"]
    assert all(completed_call.id in str(item) for item in items[:2])
    assert completed_call.name in str(items[1])
    assert '{"ok":true}' in str(items[1])
    assert "Return the final answer as JSON." in str(items[2])
    assert "tools" not in client.calls[0]


async def test_openai_responses_adapter_rejects_malformed_tool_call() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="provider_call_1",
                    arguments='{"path":"workspace:doc.md"}',
                )
            ],
            usage={},
        )
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(provider_id="openai", provider_model="gpt-5.5"),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.NONE,
                    tool_scope=ToolScope(tools=(_tool(),)),
                    tool_use=ToolUse.REQUIRED,
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.PARSE


async def test_openai_responses_adapter_maps_forced_tool_choice() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(output_text="", output=[], usage={})
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.NONE,
                tool_scope=ToolScope(
                    tools=(_tool(),),
                    selection=ToolSelection(forced_name="read_file"),
                ),
                tool_use=ToolUse.REQUIRED,
            )
        )
    )

    assert client.calls[0]["tool_choice"] == "required"


async def test_openai_responses_adapter_maps_only_visible_tools() -> None:
    hidden_tool = ToolSpec(
        name="write_file",
        description="Write a workspace file",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
    )
    client = FakeCreateClient(
        response=SimpleNamespace(output_text="", output=[], usage={})
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.NONE,
                tool_scope=ToolScope(
                    tools=(_tool(), hidden_tool),
                    selection=ToolSelection(("read_file",)),
                ),
                tool_use=ToolUse.REQUIRED,
            )
        )
    )

    assert client.calls[0]["tools"] == [_responses_tool_payload()]


async def test_openai_responses_marks_tool_output_cache_boundary_with_override_ttl() -> (
    None
):
    client = FakeCreateClient(response=SimpleNamespace(output=[], usage={}))
    adapter = GptAdapter(provider=_provider("openai"), responses=client)
    call = ToolCallRecord(id="call_1", name="read_file", arguments={"path": "a.md"})

    await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="openai",
                provider_model="gpt-6.1",
                options={
                    "prompt_cache_mode": "explicit",
                    "prompt_cache_ttl": "30m",
                    "prompt_cache_ttls": {"trace": "12h"},
                },
            ),
            messages=MessageStack.of(
                UserMessage.from_text("Stable prefix"),
                AssistantMessage.from_tool_calls(call),
                ToolResultMessage.from_json(
                    call_id="call_1", tool_name="read_file", value={"ok": True}
                ),
            ),
            answer_format=AnswerFormat.TEXT,
            prompt_cache=PromptCache(breakpoints=(PromptCacheBreakpoint("trace", 2),)),
            tool_scope=ToolScope(tools=(_tool(),)),
            tool_use=ToolUse.REQUIRED,
        )
    )

    output = _message_payloads(
        _message_payloads(client.calls[0]["input"])[-1]["output"]
    )
    assert output[-1]["prompt_cache_breakpoint"] == {
        "mode": "explicit",
        "ttl": "12h",
    }


async def test_openai_responses_adapter_skips_text_reasoning_without_keep() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="ok",
            output=[],
            usage={},
        )
    )
    adapter = GptAdapter(
        provider=_provider("openai"),
        responses=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(
                    AssistantMessage.from_text(
                        "previous answer",
                        reasoning="local reasoning",
                    )
                ),
                answer_format=AnswerFormat.TEXT,
            )
        )
    )

    assert client.calls[0]["input"] == [
        {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "previous answer"}],
        }
    ]
