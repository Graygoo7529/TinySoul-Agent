from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from collections.abc import Mapping

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.llm.cache import PromptCache
from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
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
    assert call["tools"] == [_provider_tool_payload()]
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

    assert client.calls[0]["tool_choice"] == {
        "type": "function",
        "name": "read_file",
    }


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

    assert client.calls[0]["tools"] == [_provider_tool_payload()]


def test_chat_adapter_maps_kimi_request_payload() -> None:
    message = SimpleNamespace(content='{"ok": true}', reasoning_content="thinking")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"prompt_tokens": 10, "completion_tokens": 3},
            id="chat_1",
            model="kimi-k2.7-code",
        )
    )
    adapter = KimiProviderAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="kimi",
                provider_model="kimi-k2.7-code",
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
    assert call["model"] == "kimi-k2.7-code"
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

    assert client.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "read_file"},
    }


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


def test_kimi_adapter_validates_tool_names_and_count() -> None:
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
                tool_scope=ToolScope(
                    tools=(
                        ToolSpec(
                            name="1bad",
                            description="bad",
                            parameters={"type": "object"},
                            kind=ToolKind.ACTION,
                        ),
                    ),
                ),
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


def test_deepseek_adapter_rejects_strict_tools_without_beta_opt_in() -> None:
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


def test_openai_responses_adapter_rejects_message_reasoning_input() -> None:
    adapter = OpenAIProviderAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="openai", provider_model="gpt-5.5"),
                messages=MessageStack.of(
                    AssistantMessage.from_text("previous answer",
                        reasoning="local reasoning",
                    )
                ),
                answer_format=AnswerFormat.TEXT,
            )
        )

    assert exc.value.kind is ProviderErrorKind.CONFIG


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


def _message_payloads(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise AssertionError("Expected list of message payloads")
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise AssertionError("Expected message payload mapping")
        result.append({str(key): payload for key, payload in item.items()})
    return result

