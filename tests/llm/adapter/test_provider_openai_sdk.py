from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.llm.adapter import (
    ProviderError,
    ProviderErrorKind,
    ProviderFailureScope,
)
from tinysoul.llm.adapter import (
    ProviderRequest as ProviderRequestModel,
)
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
from tinysoul.llm.protocol.cache import PromptCache
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    ImagePart,
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
    AdapterOptions,
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
    RequestOverrides,
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


def ProviderRequest(
    *,
    model: ModelSpec,
    messages: MessageStack,
    answer_format: AnswerFormat,
    tool_use: ToolUse = ToolUse.DISABLED,
    tool_scope: ToolScope | None = None,
    prompt_cache: PromptCache | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    reasoning_effort: str | None = None,
    max_output_tokens: int | None = None,
    adapter_options: Mapping[str, object] | None = None,
    timeout_seconds: float | None = None,
) -> ProviderRequestModel:
    """Build direct adapter fixtures with options owned by ModelSpec."""

    if adapter_options is not None:
        model = ModelSpec(
            id=model.id,
            providers=model.providers,
            context_window_tokens=model.context_window_tokens,
            adapter=model.adapter,
            capabilities=model.capabilities,
            adapter_options=AdapterOptions(
                {
                    **({"variant": "k2"} if model.adapter is AdapterKind.KIMI else {}),
                    **adapter_options,
                }
            ),
            reasoning_effort=reasoning_effort,
            request_overrides=model.request_overrides,
        )
    return ProviderRequestModel(
        model=model,
        binding=model.providers[0],
        messages=messages,
        answer_format=answer_format,
        tool_use=tool_use,
        tool_scope=tool_scope or ToolScope(),
        prompt_cache=prompt_cache,
        temperature=temperature,
        top_p=top_p,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
    )


@dataclass
class FakeCreateClient:
    response: object
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


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
                    "prompt_cache_ttl": "30m",
                    "reasoning_efforts": ["high"],
                    "reasoning_summary": "auto",
                    "reasoning_keep": "encrypted",
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
                "prompt_cache_ttl": "30m",
                "reasoning_efforts": ["high"],
                "reasoning_summary": "auto",
                "reasoning_keep": "encrypted",
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
    assert response.usage == {"input_tokens": 10, "output_tokens": 3}


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
                adapter_options={"reasoning_efforts": ["none"]},
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
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
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
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
        )
    )

    assert response.reasoning is not None
    assert response.reasoning.summary == "summary"
    assert response.reasoning.content is None
    assert response.reasoning.native_parts == (
        {key: value for key, value in provider_item.items() if key != "status"},
    )


async def test_openai_responses_adapter_rejects_text_reasoning_keep() -> None:
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
                    adapter_options={"reasoning_keep": "content"},
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
                "reasoning_keep": "content",
            },
        )
    )

    call = client.calls[0]
    assert call["model"] == "kimi-for-coding-highspeed"
    assert call["temperature"] == pytest.approx(0.2)
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
    assert response.reasoning.content == "thinking"
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
                    "reasoning_keep": "content",
                    "reasoning_efforts": ["max"],
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
                "reasoning_keep": "content",
                "reasoning_efforts": ["max"],
            },
            reasoning_effort="max",
        )
    )

    call = client.calls[0]
    assert call["model"] == "k3"
    assert call["temperature"] == pytest.approx(0.2)
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
    assert response.reasoning.content == "thinking"


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
                    "reasoning_keep": "content",
                    "reasoning_efforts": ["max"],
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
                    "reasoning_keep": "content",
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
                    {"reasoning_keep": "content"} if provider_id == "deepseek" else None
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
                options={"thinking": "enabled", "reasoning_efforts": ["low"]},
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
                "reasoning_efforts": ["low"],
                "reasoning_keep": "content",
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
    assert response.reasoning.content == "reasoning"
    assert response.reasoning.summary == "reasoning"
    assert response.usage == {
        "prompt_cache_hit_tokens": 8,
        "prompt_cache_miss_tokens": 2,
    }


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
                    "reasoning_efforts": ["high"],
                    "reasoning_keep": "content",
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
                adapter_options={"thinking": "enabled", "reasoning_keep": "content"},
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
            adapter_options={"thinking": "enabled", "reasoning_keep": "content"},
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
    assert response.reasoning.content == "reasoning"
    assert response.reasoning.summary == "reasoning"
    assert response.usage == {"prompt_tokens": 10, "completion_tokens": 4}


async def test_kimi_adapter_skips_message_reasoning_without_reasoning_keep() -> None:
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


async def test_glm_adapter_skips_message_reasoning_without_reasoning_keep() -> None:
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
                adapter_options={"reasoning_efforts": ["max"]},
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
                "reasoning_keep": "content",
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
    assert response.reasoning.content == "reasoning"
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
                    "reasoning_keep": "content",
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


async def test_minimax_adapter_extracts_reasoning_details() -> None:
    message = SimpleNamespace(
        content="ok",
        reasoning_details=[
            {"text": "step 1"},
            SimpleNamespace(text="step 2"),
        ],
    )
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = MiniMaxAdapter(
        provider=_provider("minimax"),
        completions=client,
    )

    response = await adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="minimax", provider_model="MiniMax-M3"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
            adapter_options={
                "thinking": "adaptive",
                "reasoning_split": True,
            },
        )
    )

    assert response.reasoning is not None
    assert response.reasoning.content == "step 1\nstep 2"
    assert response.reasoning.summary == "step 1\nstep 2"


async def test_chat_providers_report_invalid_reasoning_keep_as_provider_error() -> None:
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
                        adapter_options={"reasoning_keep": "forever"},
                    )
                )
            )

        assert exc.value.kind is ProviderErrorKind.CONFIG


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
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


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
                adapter_options={"reasoning_keep": "content"},
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
                    adapter_options={"reasoning_keep": "content"},
                )
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG
    assert client.calls == []


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


def _provider(provider_id: str) -> ProviderSpec:
    adapter = {
        "kimi": AdapterKind.KIMI,
        "kimi_coding": AdapterKind.KIMI,
        "deepseek": AdapterKind.DEEPSEEK,
        "glm": AdapterKind.GLM,
        "minimax": AdapterKind.MINIMAX,
        "openai": AdapterKind.GPT,
    }.get(provider_id, AdapterKind.OPENAI_CHAT)
    return ProviderSpec(
        id=provider_id,
        endpoints=(
            ProviderEndpoint(
                ApiMode.OPENAI_RESPONSES
                if adapter is AdapterKind.GPT
                else ApiMode.OPENAI_CHAT,
                "https://example.test/v1",
            ),
        ),
        api_key_envs=("API_KEY",),
    )


def _model(
    *,
    provider_id: str,
    provider_model: str,
    options: dict[str, object] | None = None,
    reasoning_effort: str | None = None,
    top_p: float | None = None,
) -> ModelSpec:
    adapter = {
        "kimi": AdapterKind.KIMI,
        "kimi_coding": AdapterKind.KIMI,
        "deepseek": AdapterKind.DEEPSEEK,
        "glm": AdapterKind.GLM,
        "minimax": AdapterKind.MINIMAX,
        "openai": AdapterKind.GPT,
    }.get(provider_id, AdapterKind.OPENAI_CHAT)
    return ModelSpec(
        id=provider_model.replace(".", "_"),
        providers=(ModelProviderBinding(provider_id, provider_model),),
        context_window_tokens=262_144,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.IMAGE_INPUT,
                ModelCapability.IMAGE_REMOTE_URL,
                ModelCapability.JSON_OBJECT_OUTPUT,
                ModelCapability.PROMPT_CACHE,
            }
        ),
        adapter_options=AdapterOptions(
            {
                **({"variant": "k2"} if adapter is AdapterKind.KIMI else {}),
                **(options or {}),
            }
        ),
        reasoning_effort=reasoning_effort,
        request_overrides=RequestOverrides(top_p=top_p),
        adapter=adapter,
    )


def _tool() -> ToolSpec:
    return ToolSpec(
        name="read_file",
        description="Read a workspace file",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        kind=ToolKind.ACTION,
    )


def _provider_tool_payload() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a workspace file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    }


def _write_provider_tool_payload() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a workspace file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    }


def _responses_tool_payload() -> dict[str, object]:
    return {
        "type": "function",
        "name": "read_file",
        "description": "Read a workspace file",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
    }


def _message_payloads(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise AssertionError("Expected list of message payloads")
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise AssertionError("Expected message payload mapping")
        result.append({str(key): payload for key, payload in item.items()})
    return result


def _mapping_payload(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError("Expected nested mapping payload")
    return {str(key): payload for key, payload in value.items()}
