from __future__ import annotations
from collections.abc import Callable
from types import SimpleNamespace
import pytest
from tinysoul.llm.adapter import ProviderError, ProviderErrorKind
from tinysoul.llm.adapter.models.deepseek import DeepSeekAdapter
from tinysoul.llm.adapter.models.glm import GlmAdapter
from tinysoul.llm.adapter.models.gpt import GptAdapter
from tinysoul.llm.adapter.models.kimi import KimiAdapter
from tinysoul.llm.adapter.models.minimax import MiniMaxAdapter
from tinysoul.llm.adapter.openai.chat import OpenAIChatAdapter
from tinysoul.llm.config.loader import (
    AdapterKind,
    ApiMode,
    ProviderEndpoint,
    ProviderSpec,
)
from tinysoul.llm.protocol.cache import PromptCache, PromptCacheBreakpoint
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    ImageUrlPart,
    JsonPart,
    Message,
    MessageStack,
    SystemMessage,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.protocol.models import (
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
)
from tinysoul.llm.protocol.responses import AnswerFormat, ResponseStopReason
from tinysoul.llm.protocol.tools import (
    ToolCallRecord,
    ToolKind,
    ToolResultStatus,
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


async def test_openai_sdk_adapters_normalize_output_limit_stop_reason() -> None:
    responses = GptAdapter(
        provider=_provider("openai"),
        responses=FakeCreateClient(
            response=SimpleNamespace(
                output_text="partial",
                output=[],
                usage={},
                status="incomplete",
                incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            )
        ),
    )
    chat = OpenAIChatAdapter(
        provider=_provider("compatible"),
        completions=FakeCreateClient(
            response=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="partial"),
                        finish_reason="length",
                    )
                ],
                usage={},
            )
        ),
    )
    request = ProviderRequest(
        model=_model(provider_id="openai", provider_model="test"),
        messages=MessageStack.of(UserMessage.from_text("write")),
        answer_format=AnswerFormat.TEXT,
    )

    assert (
        await responses.invoke(request)
    ).stop_reason is ResponseStopReason.OUTPUT_LIMIT
    chat_request = ProviderRequest(
        model=_model(provider_id="compatible", provider_model="test"),
        messages=request.messages,
        answer_format=AnswerFormat.TEXT,
    )
    assert (
        await chat.invoke(chat_request)
    ).stop_reason is ResponseStopReason.OUTPUT_LIMIT


async def test_openai_provider_rejects_raw_reasoning_table() -> None:
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
                    adapter_options={"reasoning": {"effort": "high"}},
                )
            )
        )
    assert exc.value.kind is ProviderErrorKind.CONFIG


async def test_openai_adapter_rejects_invalid_reasoning_summary() -> None:
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
                    adapter_options={"reasoning_summary": "full"},
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


@pytest.mark.parametrize("api_mode", ("responses", "chat"))
@pytest.mark.parametrize("exchange", ("partial", "interleaved", "mismatched", "orphan"))
async def test_adapter_preserves_non_native_tool_history(
    api_mode: str, exchange: str
) -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="done",
            output=[],
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=[]))
            ],
            usage={},
        )
    )
    provider_id = "openai" if api_mode == "responses" else "compatible"
    adapter = (
        GptAdapter(provider=_provider(provider_id), responses=client)
        if api_mode == "responses"
        else OpenAIChatAdapter(provider=_provider(provider_id), completions=client)
    )
    call = ToolCallRecord(
        id="call_inspect", name="core.context.inspect", arguments={"ref": "target-ref"}
    )
    pending = ToolCallRecord(
        id="call_pending", name="workspace.list", arguments={"query": "pending-query"}
    )
    history: list[Message] = []
    if exchange != "orphan":
        calls = (call, pending) if exchange == "partial" else (call,)
        history.append(AssistantMessage.from_text("read intent", tool_calls=calls))
    if exchange == "interleaved":
        history.append(UserMessage.from_text("accepted append"))
    result_name = "different.tool" if exchange == "mismatched" else call.name
    history.append(
        ToolResultMessage.from_parts(
            call_id=call.id,
            tool_name=result_name,
            parts=(
                TextPart("actual result text"),
                JsonPart({"detail": "actual result data"}),
            ),
            status=ToolResultStatus.ERROR,
        )
    )
    history.append(UserMessage.from_text("next task"))
    await adapter.invoke(
        ProviderRequest(
            model=_model(provider_id=provider_id, provider_model="model"),
            messages=MessageStack.of(*history),
            answer_format=AnswerFormat.TEXT,
            tool_scope=ToolScope(tools=(_tool(),)),
            tool_use=ToolUse.OPTIONAL,
        )
    )
    wire = _message_payloads(
        client.calls[0]["input" if api_mode == "responses" else "messages"]
    )
    assert len(wire) == len(history)
    assert all("type" not in item and "tool_calls" not in item for item in wire)
    assert [item["role"] for item in wire] == [
        "assistant" if isinstance(item, AssistantMessage) else "user"
        for item in history
    ]
    if exchange != "orphan":
        assert all(
            value in str(wire[0])
            for value in ("read intent", call.id, call.name, "target-ref")
        )
    if exchange == "partial":
        assert pending.id in str(wire[0]) and "pending-query" in str(wire[0])
        assert pending.id not in str(
            wire[1:]
        )  # No fabricated result for the pending call.
    if exchange == "interleaved":
        assert "accepted append" in str(wire[1])
    assert all(
        value in str(wire[-2])
        for value in (
            call.id,
            result_name,
            "actual result text",
            "actual result data",
            "error",
        )
    )
    assert "next task" in str(wire[-1])


async def test_chat_adapter_forwards_request_timeout_to_sdk() -> None:
    message = SimpleNamespace(content="ok", tool_calls=[])
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
                    provider_model="kimi-for-coding-highspeed",
                ),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                timeout_seconds=3.5,
            )
        )
    )

    assert client.calls[0]["timeout"] == pytest.approx(3.5)


async def test_chat_adapter_maps_tools_and_tool_results() -> None:
    message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="provider_call_2",
                type="function",
                function=SimpleNamespace(
                    name="read_file",
                    arguments='{"path":"workspace:next.md"}',
                ),
            )
        ],
    )
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAIChatAdapter(
        provider=_provider("compatible"),
        completions=client,
    )
    tool_call = ToolCallRecord(
        id="provider_call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="compatible", provider_model="compatible-model"),
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
    assert call["tools"] == [_provider_tool_payload()]
    assert call["messages"] == [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "provider_call_1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"workspace:doc.md"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "provider_call_1",
            "content": '```json\n{"ok":true}\n```',
        },
    ]
    assert response.tool_calls[0].id == "provider_call_2"
    assert response.tool_calls[0].arguments == {"path": "workspace:next.md"}


async def test_openai_chat_marks_multiple_named_cache_boundaries() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage={},
        )
    )
    adapter = OpenAIChatAdapter(provider=_provider("compatible"), completions=client)

    await adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="compatible",
                provider_model="gpt-5.6",
                options={
                    "prompt_cache_mode": "explicit",
                    "prompt_cache_ttl": "30m",
                    "prompt_cache_boundaries": ["background", "working"],
                },
            ),
            messages=MessageStack.of(
                SystemMessage.from_text("Identity"),
                UserMessage.from_text("Stable background"),
                UserMessage.from_text("Working state"),
                UserMessage.from_text("Task"),
            ),
            answer_format=AnswerFormat.TEXT,
            prompt_cache=PromptCache(
                breakpoints=(
                    PromptCacheBreakpoint("background", 1),
                    PromptCacheBreakpoint("working", 2),
                )
            ),
        )
    )

    messages = _message_payloads(client.calls[0]["messages"])
    assert _message_payloads(messages[1]["content"])[-1]["prompt_cache_breakpoint"] == {
        "mode": "explicit",
    }
    assert _message_payloads(messages[2]["content"])[-1]["prompt_cache_breakpoint"] == {
        "mode": "explicit",
    }


async def test_chat_adapter_rejects_unsupported_tool_call_type() -> None:
    message = SimpleNamespace(
        content="",
        tool_calls=[SimpleNamespace(type="custom", id="call_1")],
    )
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = OpenAIChatAdapter(
        provider=_provider("compatible"),
        completions=client,
    )

    with pytest.raises(ProviderError) as exc:
        (
            await adapter.invoke(
                ProviderRequest(
                    model=_model(
                        provider_id="compatible", provider_model="compatible-model"
                    ),
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    answer_format=AnswerFormat.NONE,
                    tool_scope=ToolScope(tools=(_tool(),)),
                    tool_use=ToolUse.REQUIRED,
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.PARSE


@pytest.mark.parametrize(
    ("adapter_type", "provider_id", "provider_model"),
    (
        (DeepSeekAdapter, "deepseek", "deepseek-v4-pro"),
        (GlmAdapter, "glm", "glm-5.1"),
        (MiniMaxAdapter, "minimax", "MiniMax-M3"),
        (KimiAdapter, "kimi_coding", "kimi-for-coding-highspeed"),
    ),
)
async def test_chat_adapters_replay_multiple_complete_tool_turns(
    adapter_type: Callable[..., OpenAIChatAdapter],
    provider_id: str,
    provider_model: str,
) -> None:
    message = SimpleNamespace(content="done", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = adapter_type(
        provider=_provider(provider_id),
        completions=client,
    )
    first_call = ToolCallRecord(
        id="call_first",
        name="workspace.list",
        arguments={"query": "one"},
    )
    second_call = ToolCallRecord(
        id="call_second",
        name="workspace.read",
        arguments={"link": "workspace:one.md"},
    )
    third_call = ToolCallRecord(
        id="call_third",
        name="workspace.list",
        arguments={"query": "two"},
    )
    tools = (
        ToolSpec(
            name="workspace.list",
            description="Scan",
            parameters={"type": "object"},
            kind=ToolKind.ACTION,
        ),
        ToolSpec(
            name="workspace.read",
            description="Read",
            parameters={"type": "object"},
            kind=ToolKind.ACTION,
        ),
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id=provider_id, provider_model=provider_model),
                messages=MessageStack.of(
                    UserMessage.from_text("first turn"),
                    AssistantMessage.from_tool_calls(first_call, second_call),
                    ToolResultMessage.from_json(
                        call_id=first_call.id,
                        tool_name=first_call.name,
                        value={"scan": True},
                    ),
                    ToolResultMessage.from_json(
                        call_id=second_call.id,
                        tool_name=second_call.name,
                        value={"read": True},
                    ),
                    AssistantMessage.from_text("first result"),
                    UserMessage.from_text("second turn"),
                    AssistantMessage.from_tool_calls(third_call),
                    ToolResultMessage.from_json(
                        call_id=third_call.id,
                        tool_name=third_call.name,
                        value={"scan": True},
                    ),
                    UserMessage.from_text("final prompt"),
                ),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(tools=tools),
                tool_use=ToolUse.OPTIONAL,
                adapter_options=(
                    {"native_replay": "content"} if provider_id == "deepseek" else None
                ),
            )
        )
    )

    messages = _message_payloads(client.calls[0]["messages"])
    first_tool_calls = _message_payloads(messages[1]["tool_calls"])
    third_tool_calls = _message_payloads(messages[6]["tool_calls"])
    assert [item["role"] for item in messages] == [
        "user",
        "assistant",
        "tool",
        "tool",
        "assistant",
        "user",
        "assistant",
        "tool",
        "user",
    ]
    assert [
        _mapping_payload(item["function"])["name"] for item in first_tool_calls
    ] == ["workspace_list", "workspace_read"]
    assert messages[2]["tool_call_id"] == "call_first"
    assert messages[3]["tool_call_id"] == "call_second"
    assert _mapping_payload(third_tool_calls[0]["function"])["name"] == "workspace_list"
    assert messages[7]["tool_call_id"] == "call_third"


@pytest.mark.parametrize(
    ("adapter_type", "provider_id", "provider_model"),
    (
        (DeepSeekAdapter, "deepseek", "deepseek-v4-pro"),
        (GlmAdapter, "glm", "glm-5.1"),
        (MiniMaxAdapter, "minimax", "MiniMax-M3"),
        (KimiAdapter, "kimi_coding", "kimi-for-coding-highspeed"),
    ),
)
async def test_chat_adapters_project_disabled_tool_history(
    adapter_type: Callable[..., OpenAIChatAdapter],
    provider_id: str,
    provider_model: str,
) -> None:
    message = SimpleNamespace(content="done", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = adapter_type(
        provider=_provider(provider_id),
        completions=client,
    )
    call = ToolCallRecord(id="call_disabled", name="workspace.list", arguments={})

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id=provider_id, provider_model=provider_model),
                messages=MessageStack.of(
                    AssistantMessage.from_tool_calls(call),
                    ToolResultMessage.from_json(
                        call_id=call.id,
                        tool_name=call.name,
                        value={"ok": True},
                    ),
                    UserMessage.from_text("continue"),
                ),
                answer_format=AnswerFormat.TEXT,
                tool_use=ToolUse.DISABLED,
            )
        )
    )

    messages = _message_payloads(client.calls[0]["messages"])
    assert [item["role"] for item in messages] == ["assistant", "user", "user"]
    assert all(call.id in str(item) for item in messages[:2])
    assert call.name in str(messages[1]) and '{"ok":true}' in str(messages[1])
    assert all("tool_calls" not in item for item in messages)
    assert "tools" not in client.calls[0]


async def test_chat_adapter_maps_forced_tool_choice() -> None:
    message = SimpleNamespace(content=None, tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = OpenAIChatAdapter(
        provider=_provider("compatible"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(
                    provider_id="compatible", provider_model="compatible-model"
                ),
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


async def test_chat_providers_report_invalid_native_replay_as_provider_error() -> None:
    for adapter, provider_id, provider_model in (
        (
            KimiAdapter(
                provider=_provider("kimi"),
                completions=FakeCreateClient(response=object()),
            ),
            "kimi",
            "kimi-k2.7-code",
        ),
        (
            DeepSeekAdapter(
                provider=_provider("deepseek"),
                completions=FakeCreateClient(response=object()),
            ),
            "deepseek",
            "deepseek-v4-pro",
        ),
        (
            GlmAdapter(
                provider=_provider("glm"),
                completions=FakeCreateClient(response=object()),
            ),
            "glm",
            "glm-5.1",
        ),
        (
            MiniMaxAdapter(
                provider=_provider("minimax"),
                completions=FakeCreateClient(response=object()),
            ),
            "minimax",
            "MiniMax-M3",
        ),
    ):
        with pytest.raises(ProviderError) as exc:
            (
                await adapter.invoke(
                    ProviderRequest(
                        model=_model(
                            provider_id=provider_id,
                            provider_model=provider_model,
                        ),
                        messages=MessageStack.of(
                            AssistantMessage.from_text(
                                "previous answer",
                                reasoning="trace",
                            )
                        ),
                        answer_format=AnswerFormat.TEXT,
                        adapter_options={"native_replay": "forever"},
                    )
                )
            )

        assert exc.value.kind is ProviderErrorKind.CONFIG


async def test_adapter_skips_native_json_and_cache_when_model_lacks_capability() -> (
    None
):
    message = SimpleNamespace(content='{"ok": true}')
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAIChatAdapter(
        provider=_provider("compatible"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=ModelSpec(
                    id="text_model",
                    providers=(ModelProviderBinding("compatible", "text-model"),),
                    context_window_tokens=262_144,
                    adapter=AdapterKind.OPENAI_CHAT,
                    capabilities=frozenset({ModelCapability.TEXT_INPUT}),
                ),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.JSON_OBJECT,
                prompt_cache=PromptCache("prefix"),
            )
        )
    )

    call = client.calls[0]
    assert "response_format" not in call
    assert "prompt_cache_key" not in call


async def test_generic_chat_maps_prompt_cache_intent() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAIChatAdapter(
        provider=_provider("compatible"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(
                    provider_id="compatible", provider_model="compatible-model"
                ),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                prompt_cache=PromptCache("stable-prefix"),
            )
        )
    )

    assert client.calls[0]["prompt_cache_key"] == "stable-prefix"


async def test_adapter_maps_remote_image_url_part() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAIChatAdapter(
        provider=_provider("compatible"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="compatible", provider_model="gpt-5.5"),
                messages=MessageStack.of(
                    UserMessage.from_parts(
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
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.test/image.png"},
                }
            ],
        }
    ]


async def test_chat_adapter_maps_text_and_json_parts_as_visible_text() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAIChatAdapter(
        provider=_provider("compatible"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(
                    provider_id="compatible", provider_model="compatible-model"
                ),
                messages=MessageStack.of(
                    UserMessage.from_parts(
                        TextPart("工具返回如下："),
                        JsonPart(
                            {
                                "kind": "action_result",
                                "result": {"weather": "晴"},
                            }
                        ),
                    )
                ),
                answer_format=AnswerFormat.TEXT,
            )
        )
    )

    assert client.calls[0]["messages"] == [
        {
            "role": "user",
            "content": (
                "工具返回如下：\n\n```json\n"
                '{"kind":"action_result","result":{"weather":"晴"}}\n```'
            ),
        }
    ]


async def test_compatible_chat_adapter_does_not_map_message_reasoning() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAIChatAdapter(
        provider=_provider("compatible"),
        completions=client,
    )

    (
        await adapter.invoke(
            ProviderRequest(
                model=_model(
                    provider_id="compatible", provider_model="compatible-model"
                ),
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

    assert client.calls[0]["messages"] == [
        {"role": "assistant", "content": "previous answer"}
    ]


async def test_provider_option_rejects_unknown_key() -> None:
    adapter = OpenAIChatAdapter(
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
                    adapter_options={"unknown": "value"},
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_provider_spec_reports_missing_api_key() -> None:
    provider = ProviderSpec(
        id="openai",
        endpoints=(
            ProviderEndpoint(ApiMode.OPENAI_RESPONSES, "https://api.openai.com/v1"),
        ),
        api_key_envs=("OPENAI_API_KEY",),
    )

    with pytest.raises(Exception):
        provider.resolve_api_key({})
