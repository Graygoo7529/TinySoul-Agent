from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from collections.abc import Callable, Mapping

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.llm.cache import PromptCache
from tinysoul.llm.config import ProviderAdapterKind, ProviderApiStyle, ProviderSpec
from tinysoul.llm.messages import (
    AssistantMessage,
    ImagePart,
    ImageUrlPart,
    JsonPart,
    MessageStack,
    SystemMessage,
    TextPart,
    ToolResultMessage,
    UserMessage,
)
from tinysoul.llm.models import ModelCapability, ModelSpec, ProviderOptions
from tinysoul.llm.provider import ProviderError, ProviderErrorKind, ProviderRequest
from tinysoul.llm.provider.deepseek import DeepSeekProviderAdapter
from tinysoul.llm.provider.factory import build_provider_registry
from tinysoul.llm.provider.glm import GlmProviderAdapter
from tinysoul.llm.provider.kimi import KimiProviderAdapter
from tinysoul.llm.provider.minimax import MiniMaxProviderAdapter
from tinysoul.llm.provider.open_ai import OpenAIProviderAdapter
from tinysoul.llm.provider.openai_sdk import (
    OpenAICompatibleChatAdapter,
    OpenAIResponsesAdapter,
)
from tinysoul.llm.reasoning import Reasoning
from tinysoul.llm.responses import AnswerFormat
from tinysoul.llm.tools import (
    ToolCallRecord,
    ToolKind,
    ToolScope,
    ToolSelection,
    ToolSpec,
    ToolUse,
)


@dataclass
class FakeCreateClient:
    response: object
    calls: list[dict[str, object]] = field(default_factory=list)

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


def test_openai_responses_adapter_maps_request_payload() -> None:
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
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="openai",
                provider_model="gpt-5.5",
                options={
                    "prompt_cache_retention": "24h",
                    "reasoning_effort": "high",
                    "reasoning_summary": "auto",
                    "reasoning_keep": "encrypted",
                    "verbosity": "medium",
                },
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
            provider_options={
                "prompt_cache_retention": "24h",
                "reasoning_effort": "high",
                "reasoning_summary": "auto",
                "reasoning_keep": "encrypted",
                "verbosity": "medium",
            },
        )
    )

    call = client.calls[0]
    assert call["model"] == "gpt-5.5"
    assert call["temperature"] == pytest.approx(0.2)
    assert call["max_output_tokens"] == 256
    assert call["prompt_cache_key"] == "stable-prefix"
    assert call["prompt_cache_retention"] == "24h"
    assert call["reasoning"] == {"effort": "high", "summary": "auto"}
    assert call["include"] == ["reasoning.encrypted_content"]
    assert call["text"] == {
        "format": {"type": "json_object"},
        "verbosity": "medium",
    }
    assert "reasoning_effort" not in call
    assert response.answer_text == '{"ok": true}'
    assert response.usage == {"input_tokens": 10, "output_tokens": 3}


def test_openai_provider_rejects_raw_reasoning_table() -> None:
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                provider_options={"reasoning": {"effort": "high"}},
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_openai_responses_adapter_applies_request_overrides() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(output_text="ok", output=[], usage={})
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="openai",
                provider_model="gpt-5.5",
                options={
                    "request_overrides": {
                        "temperature": 1.0,
                        "max_output_tokens": 128,
                    }
                },
            ),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
            temperature=0.2,
            max_output_tokens=256,
            provider_options={
                "request_overrides": {
                    "temperature": 1.0,
                    "max_output_tokens": 128,
                }
            },
        )
    )

    call = client.calls[0]
    assert call["temperature"] == pytest.approx(1.0)
    assert call["max_output_tokens"] == 128


def test_openai_responses_adapter_extracts_reasoning_content() -> None:
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
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
        )
    )

    assert response.reasoning is not None
    assert response.reasoning.summary == "summary\ndetail"


def test_openai_responses_adapter_extracts_encrypted_reasoning_items() -> None:
    encrypted_item: JsonObject = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "summary"}],
        "encrypted_content": "encrypted-state",
    }
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="done",
            output=[encrypted_item],
            usage={},
        )
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
        )
    )

    assert response.reasoning is not None
    assert response.reasoning.summary == "summary"
    assert response.reasoning.content is None
    assert response.reasoning.encrypted_items == (encrypted_item,)


def test_openai_responses_adapter_replays_encrypted_reasoning_items() -> None:
    encrypted_item: JsonObject = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [],
        "encrypted_content": "encrypted-state",
    }
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="ok",
            output=[],
            usage={},
        )
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(
                AssistantMessage.from_text("previous answer",
                    reasoning=Reasoning(encrypted_items=(encrypted_item,)),
                ),
                UserMessage.from_text("continue"),
            ),
            answer_format=AnswerFormat.TEXT,
            provider_options={"reasoning_keep": "encrypted"},
        )
    )

    assert client.calls[0]["input"] == [
        encrypted_item,
        {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "previous answer"}],
        },
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "continue"}],
        },
    ]
    assert client.calls[0]["include"] == ["reasoning.encrypted_content"]


def test_openai_responses_adapter_skips_encrypted_reasoning_without_keep() -> None:
    encrypted_item: JsonObject = {
        "type": "reasoning",
        "encrypted_content": "encrypted-state",
    }
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="ok",
            output=[],
            usage={},
        )
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(
                AssistantMessage.from_text("previous answer",
                    reasoning=Reasoning(encrypted_items=(encrypted_item,)),
                )
            ),
            answer_format=AnswerFormat.TEXT,
        )
    )

    assert client.calls[0]["input"] == [
        {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "previous answer"}],
        }
    ]
    assert "include" not in client.calls[0]


def test_openai_responses_adapter_replays_encrypted_reasoning_when_text_content_exists() -> None:
    encrypted_item: JsonObject = {
        "type": "reasoning",
        "encrypted_content": "encrypted-state",
    }
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="ok",
            output=[],
            usage={},
        )
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(
                AssistantMessage.from_text(
                    "previous answer",
                    reasoning=Reasoning(
                        content="local reasoning",
                        encrypted_items=(encrypted_item,),
                    ),
                )
            ),
            answer_format=AnswerFormat.TEXT,
            provider_options={"reasoning_keep": "encrypted"},
        )
    )

    assert client.calls[0]["input"] == [
        encrypted_item,
        {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "previous answer"}],
        },
    ]
    assert client.calls[0]["include"] == ["reasoning.encrypted_content"]


def test_openai_responses_adapter_rejects_text_reasoning_keep() -> None:
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                provider_options={"reasoning_keep": "content"},
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_openai_adapter_rejects_invalid_reasoning_summary() -> None:
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                provider_options={"reasoning_summary": "full"},
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_openai_responses_adapter_maps_text_and_json_as_input_text() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="ok",
            output=[],
            usage={},
        )
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    adapter.invoke(
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

    assert client.calls[0]["input"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        '工具返回如下：\n\n```json\n'
                        '{"ok":true,"source":"tool_result"}\n```'
                    ),
                }
            ],
        }
    ]


def test_openai_responses_adapter_maps_tools_and_tool_results() -> None:
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
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )
    tool_call = ToolCallRecord(
        id="provider_call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
    )

    response = adapter.invoke(
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


def test_openai_responses_adapter_maps_dotted_tool_names_round_trip() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="",
            output=[
                SimpleNamespace(
                    type="function_call",
                    call_id="provider_call_1",
                    name="workspace_scan",
                    arguments="{}",
                )
            ],
            usage={},
        )
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )
    tool = ToolSpec(
        name="workspace.scan",
        description="Scan the workspace",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
    )

    response = adapter.invoke(
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
            "name": "workspace_scan",
            "description": "Scan the workspace",
            "parameters": {"type": "object"},
        }
    ]
    assert response.tool_calls[0].name == "workspace.scan"


def test_openai_responses_adapter_omits_incomplete_tool_exchange_history() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(output_text='{"text":"hello"}', output=[], usage={})
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )
    unresolved_call = ToolCallRecord(
        id="call_unresolved",
        name="core.answer",
        arguments={},
    )

    adapter.invoke(
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

    assert client.calls[0]["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Return the final answer as JSON."}
            ],
        }
    ]
    assert "tools" not in client.calls[0]


def test_openai_responses_adapter_renders_tool_result_as_disabled_context() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(output_text='{"text":"hello"}', output=[], usage={})
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )
    completed_call = ToolCallRecord(
        id="call_completed",
        name="core.answer",
        arguments={},
    )

    adapter.invoke(
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

    assert client.calls[0]["input"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Tool result for core.answer:\n"
                        '```json\n{"ok":true}\n```'
                    ),
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Return the final answer as JSON."}
            ],
        },
    ]
    assert "tools" not in client.calls[0]


def test_openai_responses_adapter_drops_reasoning_with_suppressed_tool_turn() -> None:
    encrypted_item: JsonObject = {
        "id": "rs_tool_turn",
        "type": "reasoning",
        "summary": [],
        "encrypted_content": "opaque-state",
    }
    client = FakeCreateClient(
        response=SimpleNamespace(output_text='{"text":"hello"}', output=[], usage={})
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )
    unresolved_call = ToolCallRecord(
        id="call_unresolved_reasoning",
        name="core.answer",
        arguments={},
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(
                AssistantMessage.from_parts(
                    reasoning=Reasoning(encrypted_items=(encrypted_item,)),
                    tool_calls=(unresolved_call,),
                ),
                UserMessage.from_text("Return JSON."),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            tool_use=ToolUse.DISABLED,
            provider_options={"reasoning_keep": "encrypted"},
        )
    )

    assert client.calls[0]["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "Return JSON."}],
        }
    ]


def test_openai_responses_adapter_replays_only_complete_tool_turns() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(output_text='{"text":"hello"}', output=[], usage={})
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )
    first_call = ToolCallRecord(id="call_first", name="workspace.scan", arguments={})
    second_call = ToolCallRecord(id="call_second", name="workspace.read", arguments={})

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(
                UserMessage.from_text("first"),
                AssistantMessage.from_tool_calls(first_call, second_call),
                ToolResultMessage.from_json(
                    call_id=first_call.id,
                    tool_name=first_call.name,
                    value={"ok": True},
                ),
                UserMessage.from_text("second"),
            ),
            answer_format=AnswerFormat.TEXT,
            tool_use=ToolUse.OPTIONAL,
            tool_scope=ToolScope(
                tools=(
                    ToolSpec(
                        name="workspace.scan",
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
            ),
        )
    )

    assert client.calls[0]["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "first"}],
        },
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "second"}],
        },
    ]


def test_chat_adapter_rejects_partial_or_mismatched_native_tool_turn() -> None:
    message = SimpleNamespace(content="done", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiProviderAdapter(
        provider=_provider("kimi_coding", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )
    first_call = ToolCallRecord(id="call_first", name="workspace.scan", arguments={})
    second_call = ToolCallRecord(id="call_second", name="workspace.read", arguments={})

    adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="kimi_coding",
                provider_model="kimi-for-coding-highspeed",
            ),
            messages=MessageStack.of(
                AssistantMessage.from_tool_calls(first_call, second_call),
                ToolResultMessage.from_json(
                    call_id=first_call.id,
                    tool_name="workspace.read",
                    value={"wrong": True},
                ),
                UserMessage.from_text("continue"),
            ),
            answer_format=AnswerFormat.TEXT,
            tool_use=ToolUse.OPTIONAL,
            tool_scope=ToolScope(
                tools=(
                    ToolSpec(
                        name="workspace.scan",
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
            ),
        )
    )

    assert client.calls[0]["messages"] == [
        {"role": "user", "content": "continue"},
    ]


def test_openai_responses_adapter_rejects_malformed_tool_call() -> None:
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
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.NONE,
                tool_scope=ToolScope(tools=(_tool(),)),
                tool_use=ToolUse.REQUIRED,
            )
        )

    assert exc.value.kind is ProviderErrorKind.PARSE


def test_openai_responses_adapter_maps_forced_tool_choice() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(output_text="", output=[], usage={})
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    adapter.invoke(
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

    assert client.calls[0]["tool_choice"] == "required"


def test_openai_responses_adapter_maps_only_visible_tools() -> None:
    hidden_tool = ToolSpec(
        name="write_file",
        description="Write a workspace file",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
    )
    client = FakeCreateClient(
        response=SimpleNamespace(output_text="", output=[], usage={})
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    adapter.invoke(
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

    assert client.calls[0]["tools"] == [_responses_tool_payload()]


def test_kimi_k2_7_adapter_maps_coding_plan_request_payload() -> None:
    message = SimpleNamespace(content='{"ok": true}', reasoning_content="thinking")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_tokens": 10, "completion_tokens": 3},
            id="chat_1",
            model="kimi-for-coding-highspeed",
        )
    )
    adapter = KimiProviderAdapter(
        provider=_provider("kimi_coding", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="kimi_coding",
                provider_model="kimi-for-coding-highspeed",
                options={"thinking": "enabled"},
            ),
            messages=MessageStack.of(
                UserMessage.from_text("hello"),
                AssistantMessage.from_text('{"draft": true}',
                    reasoning="thinking trace",
                ),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            prompt_cache=PromptCache("kimi-prefix"),
            temperature=0.2,
            max_output_tokens=128,
            provider_options={
                "thinking": "enabled",
                "reasoning_keep": "content",
                "request_overrides": {"temperature": 1.0},
            },
        )
    )

    call = client.calls[0]
    assert call["model"] == "kimi-for-coding-highspeed"
    assert call["temperature"] == pytest.approx(1.0)
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


def test_kimi_k3_adapter_maps_reasoning_without_k2_thinking() -> None:
    message = SimpleNamespace(content='{"ok": true}', reasoning_content="thinking")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_tokens": 10, "completion_tokens": 3},
            id="chat_k3_1",
            model="k3",
        )
    )
    adapter = KimiProviderAdapter(
        provider=_provider("kimi_coding", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="kimi_coding",
                provider_model="k3",
                options={"reasoning_keep": "content", "reasoning_effort": "max"},
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
            provider_options={
                "reasoning_keep": "content",
                "reasoning_effort": "max",
                "request_overrides": {"temperature": 1.0},
            },
        )
    )

    call = client.calls[0]
    assert call["model"] == "k3"
    assert call["temperature"] == pytest.approx(1.0)
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


def test_chat_adapter_forwards_request_timeout_to_sdk() -> None:
    message = SimpleNamespace(content="ok", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiProviderAdapter(
        provider=_provider("kimi_coding", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
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

    assert client.calls[0]["timeout"] == pytest.approx(3.5)


def test_kimi_k3_adapter_rejects_k2_thinking_option() -> None:
    adapter = KimiProviderAdapter(
        provider=_provider("kimi_coding", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="kimi_coding", provider_model="k3"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                provider_options={"thinking": "enabled"},
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_chat_adapter_maps_tools_and_tool_results() -> None:
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
    adapter = OpenAICompatibleChatAdapter(
        provider=_provider("generic", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )
    tool_call = ToolCallRecord(
        id="provider_call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="generic", provider_model="generic-model"),
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


def test_chat_adapter_rejects_unsupported_tool_call_type() -> None:
    message = SimpleNamespace(
        content="",
        tool_calls=[SimpleNamespace(type="custom", id="call_1")],
    )
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = OpenAICompatibleChatAdapter(
        provider=_provider("generic", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="generic", provider_model="generic-model"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.NONE,
                tool_scope=ToolScope(tools=(_tool(),)),
                tool_use=ToolUse.REQUIRED,
            )
        )

    assert exc.value.kind is ProviderErrorKind.PARSE


def test_kimi_k3_adapter_replays_reasoning_with_tool_calls_and_results() -> None:
    message = SimpleNamespace(content="ok", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiProviderAdapter(
        provider=_provider("kimi_coding", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )
    tool_call = ToolCallRecord(
        id="provider_call_1",
        name="workspace.scan",
        arguments={"path": "workspace:doc.md"},
    )
    tool = ToolSpec(
        name="workspace.scan",
        description="Scan the workspace",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="kimi_coding", provider_model="k3"),
            messages=MessageStack.of(
                AssistantMessage.from_parts(
                    reasoning="tool reasoning",
                    tool_calls=(tool_call,),
                ),
                ToolResultMessage.from_json(
                    call_id="provider_call_1",
                    tool_name="workspace.scan",
                    value={"ok": True},
                ),
            ),
            answer_format=AnswerFormat.TEXT,
            tool_scope=ToolScope(tools=(tool,)),
            tool_use=ToolUse.OPTIONAL,
            provider_options={
                "reasoning_keep": "content",
                "reasoning_effort": "max",
            },
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
                        "name": "workspace_scan",
                        "arguments": '{"path":"workspace:doc.md"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "provider_call_1",
            "content": '```json\n{"ok":true}\n```',
            "name": "workspace_scan",
        }
    ]
    assert client.calls[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "workspace_scan",
                "description": "Scan the workspace",
                "parameters": {"type": "object"},
            },
        }
    ]
    assert client.calls[0]["reasoning_effort"] == "max"


def test_kimi_adapter_omits_unresolved_tool_call_but_keeps_reasoning() -> None:
    message = SimpleNamespace(
        content='{"text":"\u4f60\u597d"}',
        reasoning_content="answer reasoning",
        tool_calls=[],
    )
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiProviderAdapter(
        provider=_provider("kimi_coding", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )
    unresolved_call = ToolCallRecord(
        id="tool_5EPQk3dnZPdE13NVvWmuVd1S",
        name="core.answer",
        arguments={"guide_blocks": [{"text": "Answer the user."}]},
    )

    adapter.invoke(
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
            provider_options={
                "thinking": "enabled",
                "reasoning_keep": "content",
            },
        )
    )

    assert client.calls[0]["messages"] == [
        {"role": "user", "content": "Return the final answer as JSON."},
    ]
    assert "tools" not in client.calls[0]


def test_kimi_adapter_renders_tool_result_as_disabled_context() -> None:
    message = SimpleNamespace(
        content='{"text":"\u4f60\u597d"}',
        reasoning_content="answer reasoning",
        tool_calls=[],
    )
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiProviderAdapter(
        provider=_provider("kimi_coding", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )
    completed_call = ToolCallRecord(
        id="tool_5EPQk3dnZPdE13NVvWmuVd1S",
        name="core.answer",
        arguments={"guide_blocks": [{"text": "Answer the user."}]},
    )

    adapter.invoke(
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
            provider_options={"thinking": "enabled"},
        )
    )

    assert client.calls[0]["messages"] == [
        {
            "role": "user",
            "content": (
                "Tool result for core.answer:\n"
                '```json\n{"ok":true}\n```'
            ),
        },
        {"role": "user", "content": "Return the final answer as JSON."},
    ]
    assert "tools" not in client.calls[0]


@pytest.mark.parametrize(
    ("adapter_type", "provider_id", "provider_model"),
    (
        (DeepSeekProviderAdapter, "deepseek", "deepseek-v4-pro"),
        (GlmProviderAdapter, "glm", "glm-5.1"),
        (MiniMaxProviderAdapter, "minimax", "MiniMax-M3"),
        (KimiProviderAdapter, "kimi_coding", "kimi-for-coding-highspeed"),
    ),
)
def test_chat_adapters_replay_multiple_complete_tool_turns(
    adapter_type: Callable[..., OpenAICompatibleChatAdapter],
    provider_id: str,
    provider_model: str,
) -> None:
    message = SimpleNamespace(content="done", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = adapter_type(
        provider=_provider(provider_id, ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )
    first_call = ToolCallRecord(
        id="call_first",
        name="workspace.scan",
        arguments={"query": "one"},
    )
    second_call = ToolCallRecord(
        id="call_second",
        name="workspace.read",
        arguments={"link": "workspace:one.md"},
    )
    third_call = ToolCallRecord(
        id="call_third",
        name="workspace.scan",
        arguments={"query": "two"},
    )
    tools = (
        ToolSpec(
            name="workspace.scan",
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

    adapter.invoke(
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
    ] == ["workspace_scan", "workspace_read"]
    assert messages[2]["tool_call_id"] == "call_first"
    assert messages[3]["tool_call_id"] == "call_second"
    assert _mapping_payload(third_tool_calls[0]["function"])["name"] == "workspace_scan"
    assert messages[7]["tool_call_id"] == "call_third"


@pytest.mark.parametrize(
    ("adapter_type", "provider_id", "provider_model"),
    (
        (DeepSeekProviderAdapter, "deepseek", "deepseek-v4-pro"),
        (GlmProviderAdapter, "glm", "glm-5.1"),
        (MiniMaxProviderAdapter, "minimax", "MiniMax-M3"),
        (KimiProviderAdapter, "kimi_coding", "kimi-for-coding-highspeed"),
    ),
)
def test_chat_adapters_project_disabled_tool_history(
    adapter_type: Callable[..., OpenAICompatibleChatAdapter],
    provider_id: str,
    provider_model: str,
) -> None:
    message = SimpleNamespace(content="done", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = adapter_type(
        provider=_provider(provider_id, ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )
    call = ToolCallRecord(id="call_disabled", name="workspace.scan", arguments={})

    adapter.invoke(
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

    messages = _message_payloads(client.calls[0]["messages"])
    assert messages == [
        {
            "role": "user",
            "content": "Tool result for workspace.scan:\n```json\n{\"ok\":true}\n```",
        },
        {"role": "user", "content": "continue"},
    ]
    assert "tools" not in client.calls[0]


def test_chat_adapter_maps_forced_tool_choice() -> None:
    message = SimpleNamespace(content=None, tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = OpenAICompatibleChatAdapter(
        provider=_provider("generic", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="generic", provider_model="generic-model"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.NONE,
            tool_scope=ToolScope(
                tools=(_tool(),),
                selection=ToolSelection(forced_name="read_file"),
            ),
            tool_use=ToolUse.REQUIRED,
        )
    )

    assert client.calls[0]["tool_choice"] == "required"


@pytest.mark.parametrize(
    ("provider_model", "expected_tool_choice"),
    (("kimi-for-coding-highspeed", "auto"), ("k3", "required")),
)
def test_kimi_adapter_maps_model_specific_required_tool_choice(
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
    adapter = KimiProviderAdapter(
        provider=_provider("kimi_coding", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="kimi_coding",
                provider_model=provider_model,
            ),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
            tool_scope=ToolScope(tools=(_tool(),)),
            tool_use=ToolUse.REQUIRED,
        )
    )

    assert client.calls[0]["tool_choice"] == expected_tool_choice


def test_kimi_adapter_keeps_all_visible_tools_for_forced_tool_choice() -> None:
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
    adapter = KimiProviderAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
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

    assert client.calls[0]["tool_choice"] == "auto"
    assert client.calls[0]["tools"] == [
        _provider_tool_payload(),
        _write_provider_tool_payload(),
    ]


def test_deepseek_adapter_maps_thinking_and_reasoning_effort() -> None:
    message = SimpleNamespace(content='{"ok": true}', reasoning_content="reasoning")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_cache_hit_tokens": 8, "prompt_cache_miss_tokens": 2},
            id="chat_2",
            model="deepseek-v4-pro",
        )
    )
    adapter = DeepSeekProviderAdapter(
        provider=_provider("deepseek", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="deepseek",
                provider_model="deepseek-v4-pro",
                options={"thinking": "enabled", "reasoning_effort": "high"},
            ),
            messages=MessageStack.of(
                UserMessage.from_text("json please"),
                AssistantMessage.from_text('{"plan": "call action"}',
                    reasoning="reasoning trace",
                ),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            temperature=0.7,
            max_output_tokens=128,
            provider_options={"thinking": "enabled", "reasoning_effort": "high", "reasoning_keep": "content"},
        )
    )

    call = client.calls[0]
    assert call["model"] == "deepseek-v4-pro"
    messages = _message_payloads(call["messages"])
    assert messages[1]["reasoning_content"] == "reasoning trace"
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {"thinking": {"type": "enabled"}}
    assert call["reasoning_effort"] == "high"
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


def test_deepseek_adapter_skips_message_reasoning_without_reasoning_keep() -> None:
    message = SimpleNamespace(content="ok", reasoning_content="reasoning")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = DeepSeekProviderAdapter(
        provider=_provider("deepseek", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="deepseek", provider_model="deepseek-v4-pro"),
            messages=MessageStack.of(
                AssistantMessage.from_text("previous answer",
                    reasoning="reasoning trace",
                )
            ),
            answer_format=AnswerFormat.TEXT,
            provider_options={"thinking": "enabled", "reasoning_effort": "high"},
        )
    )

    assert client.calls[0]["messages"] == [
        {"role": "assistant", "content": "previous answer"}
    ]


def test_deepseek_adapter_maps_required_tool_choice_to_auto_with_thinking() -> None:
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
    adapter = DeepSeekProviderAdapter(
        provider=_provider("deepseek", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="deepseek", provider_model="deepseek-v4-pro"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
            tool_scope=ToolScope(tools=(_tool(),)),
            tool_use=ToolUse.REQUIRED,
            provider_options={"thinking": "enabled", "reasoning_effort": "high"},
        )
    )

    assert client.calls[0]["tool_choice"] == "auto"


def test_glm_adapter_maps_required_tool_choice_to_auto() -> None:
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
    adapter = GlmProviderAdapter(
        provider=_provider("glm", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="glm", provider_model="glm-5.1"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
            tool_scope=ToolScope(
                tools=(_tool(), write_tool),
                selection=ToolSelection(forced_name="read_file"),
            ),
            tool_use=ToolUse.REQUIRED,
            provider_options={"thinking": "enabled", "reasoning_keep": "content"},
        )
    )

    assert client.calls[0]["tool_choice"] == "auto"
    assert client.calls[0]["tools"] == [
        _provider_tool_payload(),
        _write_provider_tool_payload(),
    ]


def test_glm_adapter_rejects_strict_tool_calling() -> None:
    strict_tool = ToolSpec(
        name="read_file",
        description="Read a workspace file",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
        strict=True,
    )
    adapter = GlmProviderAdapter(
        provider=_provider("glm", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="glm", provider_model="glm-5.1"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(tools=(strict_tool,)),
                tool_use=ToolUse.REQUIRED,
                provider_options={"thinking": "enabled"},
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_glm_adapter_maps_thinking_and_max_tokens() -> None:
    message = SimpleNamespace(content='{"ok": true}', reasoning_content="reasoning")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_tokens": 10, "completion_tokens": 4},
            id="chat_3",
            model="glm-5.1",
        )
    )
    adapter = GlmProviderAdapter(
        provider=_provider("glm", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="glm",
                provider_model="glm-5.1",
                options={"thinking": "enabled"},
            ),
            messages=MessageStack.of(
                UserMessage.from_text("json please"),
                AssistantMessage.from_text('{"plan": "call action"}',
                    reasoning="reasoning trace",
                ),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            max_output_tokens=128,
            provider_options={"thinking": "enabled", "reasoning_keep": "content"},
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


def test_kimi_adapter_skips_message_reasoning_without_reasoning_keep() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = KimiProviderAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
            messages=MessageStack.of(
                AssistantMessage.from_text("previous answer",
                    reasoning="thinking trace",
                )
            ),
            answer_format=AnswerFormat.TEXT,
            provider_options={"thinking": "enabled"},
        )
    )

    assert client.calls[0]["messages"] == [
        {"role": "assistant", "content": "previous answer"}
    ]
    assert client.calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}


def test_glm_adapter_skips_message_reasoning_without_reasoning_keep() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = GlmProviderAdapter(
        provider=_provider("glm", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="glm", provider_model="glm-5.1"),
            messages=MessageStack.of(
                AssistantMessage.from_text("previous answer",
                    reasoning="thinking trace",
                )
            ),
            answer_format=AnswerFormat.TEXT,
            provider_options={"thinking": "enabled"},
        )
    )

    assert client.calls[0]["messages"] == [
        {"role": "assistant", "content": "previous answer"}
    ]
    assert client.calls[0]["extra_body"] == {
        "thinking": {"type": "enabled", "clear_thinking": True}
    }


def test_glm_adapter_maps_reasoning_effort_provider_option() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = GlmProviderAdapter(
        provider=_provider("glm", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="glm", provider_model="glm-5.2"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
            provider_options={"reasoning_effort": "max"},
        )
    )

    assert client.calls[0]["reasoning_effort"] == "max"


def test_minimax_adapter_maps_thinking_and_reasoning_split() -> None:
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
    adapter = MiniMaxProviderAdapter(
        provider=_provider("minimax", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=ModelSpec(
                id="minimax_m3",
                provider_id="minimax",
                provider_model="MiniMax-M3",
                context_window_tokens=262_144,
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
                AssistantMessage.from_text('{"plan": "continue"}',
                    reasoning="reasoning trace",
                ),
            ),
            answer_format=AnswerFormat.JSON_OBJECT,
            max_output_tokens=128,
            provider_options={
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


def test_minimax_adapter_removes_required_tool_choice() -> None:
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
    adapter = MiniMaxProviderAdapter(
        provider=_provider("minimax", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="minimax", provider_model="MiniMax-M3"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
            tool_scope=ToolScope(
                tools=(_tool(), write_tool),
                selection=ToolSelection(forced_name="read_file"),
            ),
            tool_use=ToolUse.REQUIRED,
            provider_options={
                "thinking": "adaptive",
                "reasoning_split": True,
                "reasoning_keep": "content",
            },
        )
    )

    assert "tool_choice" not in client.calls[0]
    assert client.calls[0]["tools"] == [
        _provider_tool_payload(),
        _write_provider_tool_payload(),
    ]


def test_minimax_adapter_rejects_strict_tool_calling() -> None:
    strict_tool = ToolSpec(
        name="read_file",
        description="Read a workspace file",
        parameters={"type": "object"},
        kind=ToolKind.ACTION,
        strict=True,
    )
    adapter = MiniMaxProviderAdapter(
        provider=_provider("minimax", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="minimax", provider_model="MiniMax-M3"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                tool_scope=ToolScope(tools=(strict_tool,)),
                tool_use=ToolUse.REQUIRED,
                provider_options={"thinking": "adaptive"},
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_minimax_adapter_extracts_reasoning_details() -> None:
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
    adapter = MiniMaxProviderAdapter(
        provider=_provider("minimax", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="minimax", provider_model="MiniMax-M3"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
            provider_options={
                "thinking": "adaptive",
                "reasoning_split": True,
            },
        )
    )

    assert response.reasoning is not None
    assert response.reasoning.content == "step 1\nstep 2"
    assert response.reasoning.summary == "step 1\nstep 2"


def test_chat_providers_report_invalid_reasoning_keep_as_provider_error() -> None:
    for adapter, provider_id, provider_model in (
        (
            KimiProviderAdapter(
                provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
                api_key="key",
                completions=FakeCreateClient(response=object()),
            ),
            "kimi",
            "kimi-k2.7-code",
        ),
        (
            DeepSeekProviderAdapter(
                provider=_provider("deepseek", ProviderApiStyle.OPENAI_CHAT),
                api_key="key",
                completions=FakeCreateClient(response=object()),
            ),
            "deepseek",
            "deepseek-v4-pro",
        ),
        (
            GlmProviderAdapter(
                provider=_provider("glm", ProviderApiStyle.OPENAI_CHAT),
                api_key="key",
                completions=FakeCreateClient(response=object()),
            ),
            "glm",
            "glm-5.1",
        ),
        (
            MiniMaxProviderAdapter(
                provider=_provider("minimax", ProviderApiStyle.OPENAI_CHAT),
                api_key="key",
                completions=FakeCreateClient(response=object()),
            ),
            "minimax",
            "MiniMax-M3",
        ),
    ):
        with pytest.raises(ProviderError) as exc:
            adapter.invoke(
                ProviderRequest(
                    model=_model(
                        provider_id=provider_id,
                        provider_model=provider_model,
                    ),
                    messages=MessageStack.of(
                        AssistantMessage.from_text("previous answer",
                            reasoning="trace",
                        )
                    ),
                    answer_format=AnswerFormat.TEXT,
                    provider_options={"reasoning_keep": "forever"},
                )
            )

        assert exc.value.kind is ProviderErrorKind.CONFIG


def test_kimi_adapter_rejects_partial_provider_option() -> None:
    adapter = KimiProviderAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                provider_options={"partial": True},
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_kimi_adapter_maps_dotted_tool_name_and_decodes_response() -> None:
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
    adapter = KimiProviderAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    response = adapter.invoke(
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


def test_kimi_adapter_rejects_more_than_128_visible_tools() -> None:
    adapter = KimiProviderAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
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
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.NONE,
                tool_scope=ToolScope(tools=tools),
                tool_use=ToolUse.OPTIONAL,
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_kimi_adapter_validates_only_visible_tools() -> None:
    message = SimpleNamespace(content="ok", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = KimiProviderAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
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

    assert client.calls[0]["tools"] == [_provider_tool_payload()]


def test_deepseek_adapter_rejects_strict_tools() -> None:
    adapter = DeepSeekProviderAdapter(
        provider=_provider("deepseek", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="deepseek", provider_model="deepseek-chat"),
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

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_deepseek_adapter_validates_only_visible_tools() -> None:
    message = SimpleNamespace(content="ok", tool_calls=[])
    client = FakeCreateClient(
        response=SimpleNamespace(choices=[SimpleNamespace(message=message)], usage={})
    )
    adapter = DeepSeekProviderAdapter(
        provider=_provider("deepseek", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="deepseek", provider_model="deepseek-chat"),
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
        )
    )

    assert client.calls[0]["tools"] == [_provider_tool_payload()]


def test_adapter_rejects_invalid_request_override_value() -> None:
    adapter = KimiProviderAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                provider_options={"request_overrides": {"temperature": True}},
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_adapter_skips_native_json_and_cache_when_model_lacks_capability() -> None:
    message = SimpleNamespace(content='{"ok": true}')
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAICompatibleChatAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=ModelSpec(
                id="text_model",
                provider_id="kimi",
                provider_model="text-model",
                context_window_tokens=262_144,
                capabilities=frozenset({ModelCapability.TEXT_INPUT}),
            ),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.JSON_OBJECT,
            prompt_cache=PromptCache("prefix"),
        )
    )

    call = client.calls[0]
    assert "response_format" not in call
    assert "prompt_cache_key" not in call


def test_generic_chat_adapter_does_not_map_prompt_cache_key() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAICompatibleChatAdapter(
        provider=_provider("generic", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="generic", provider_model="generic-model"),
            messages=MessageStack.of(UserMessage.from_text("hello")),
            answer_format=AnswerFormat.TEXT,
            prompt_cache=PromptCache("stable-prefix"),
        )
    )

    assert "prompt_cache_key" not in client.calls[0]


def test_adapter_maps_remote_image_url_part() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAICompatibleChatAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(
                UserMessage.from_parts(
                    ImageUrlPart(url="https://example.test/image.png"),
                )
            ),
            answer_format=AnswerFormat.TEXT,
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


def test_chat_adapter_maps_text_and_json_parts_as_visible_text() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAICompatibleChatAdapter(
        provider=_provider("generic", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="generic", provider_model="generic-model"),
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

    assert client.calls[0]["messages"] == [
        {
            "role": "user",
            "content": (
                '工具返回如下：\n\n```json\n'
                '{"kind":"action_result","result":{"weather":"晴"}}\n```'
            ),
        }
    ]


def test_generic_chat_adapter_does_not_map_message_reasoning() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAICompatibleChatAdapter(
        provider=_provider("generic", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="generic", provider_model="generic-model"),
            messages=MessageStack.of(
                AssistantMessage.from_text("previous answer",
                    reasoning="local reasoning",
                )
            ),
            answer_format=AnswerFormat.TEXT,
        )
    )

    assert client.calls[0]["messages"] == [
        {"role": "assistant", "content": "previous answer"}
    ]


def test_openai_responses_adapter_skips_text_reasoning_without_keep() -> None:
    client = FakeCreateClient(
        response=SimpleNamespace(
            output_text="ok",
            output=[],
            usage={},
        )
    )
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    adapter.invoke(
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

    assert client.calls[0]["input"] == [
        {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "previous answer"}],
        }
    ]


def test_provider_option_rejects_unknown_key() -> None:
    adapter = OpenAICompatibleChatAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
                messages=MessageStack.of(UserMessage.from_text("hello")),
                answer_format=AnswerFormat.TEXT,
                provider_options={"unknown": "value"},
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


def test_build_provider_registry_uses_first_configured_api_key() -> None:
    registry = build_provider_registry(
        (
            ProviderSpec(
                id="kimi",
                api_style=ProviderApiStyle.OPENAI_CHAT,
                base_url="https://api.moonshot.cn/v1",
                api_key_envs=("KIMI_API_KEY", "MOONSHOT_API_KEY"),
            ),
        ),
        env={"MOONSHOT_API_KEY": "moonshot"},
    )

    assert registry.get("kimi").provider_id == "kimi"


def test_build_provider_registry_supports_distinct_kimi_endpoints() -> None:
    registry = build_provider_registry(
        (
            ProviderSpec(
                id="kimi",
                adapter=ProviderAdapterKind.KIMI,
                api_style=ProviderApiStyle.OPENAI_CHAT,
                base_url="https://api.moonshot.cn/v1",
                api_key_envs=("MOONSHOT_API_KEY",),
            ),
            ProviderSpec(
                id="kimi_coding",
                adapter=ProviderAdapterKind.KIMI,
                api_style=ProviderApiStyle.OPENAI_CHAT,
                base_url="https://api.kimi.com/coding/v1",
                api_key_envs=("KIMI_CODING_API_KEY",),
            ),
        ),
        env={
            "MOONSHOT_API_KEY": "moonshot",
            "KIMI_CODING_API_KEY": "coding",
        },
    )

    assert registry.get("kimi").provider_id == "kimi"
    assert registry.get("kimi_coding").provider_id == "kimi_coding"


def test_build_provider_registry_uses_deepseek_adapter() -> None:
    registry = build_provider_registry(
        (
            ProviderSpec(
                id="deepseek",
                api_style=ProviderApiStyle.OPENAI_CHAT,
                base_url="https://api.deepseek.com",
                api_key_envs=("DEEPSEEK_API_KEY",),
            ),
        ),
        env={"DEEPSEEK_API_KEY": "deepseek"},
    )

    assert registry.get("deepseek").provider_id == "deepseek"


def test_build_provider_registry_uses_glm_adapter() -> None:
    registry = build_provider_registry(
        (
            ProviderSpec(
                id="glm",
                api_style=ProviderApiStyle.OPENAI_CHAT,
                base_url="https://open.bigmodel.cn/api/paas/v4",
                api_key_envs=("GLM_API_KEY",),
            ),
        ),
        env={"GLM_API_KEY": "glm"},
    )

    assert registry.get("glm").provider_id == "glm"


def test_build_provider_registry_uses_minimax_adapter() -> None:
    registry = build_provider_registry(
        (
            ProviderSpec(
                id="minimax",
                api_style=ProviderApiStyle.OPENAI_CHAT,
                base_url="https://api.minimaxi.com/v1",
                api_key_envs=("MINIMAX_API_KEY",),
            ),
        ),
        env={"MINIMAX_API_KEY": "minimax"},
    )

    assert registry.get("minimax").provider_id == "minimax"


def test_provider_spec_reports_missing_api_key() -> None:
    provider = ProviderSpec(
        id="openai",
        api_style=ProviderApiStyle.OPENAI_RESPONSES,
        base_url="https://api.openai.com/v1",
        api_key_envs=("OPENAI_API_KEY",),
    )

    with pytest.raises(Exception):
        provider.resolve_api_key({})


def _provider(provider_id: str, api_style: ProviderApiStyle) -> ProviderSpec:
    return ProviderSpec(
        id=provider_id,
        api_style=api_style,
        base_url="https://example.test/v1",
        api_key_envs=("API_KEY",),
    )


def _model(
    *,
    provider_id: str,
    provider_model: str,
    options: dict[str, object] | None = None,
) -> ModelSpec:
    return ModelSpec(
        id=provider_model.replace(".", "_"),
        provider_id=provider_id,
        provider_model=provider_model,
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
        provider_options=ProviderOptions(options or {}),
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

