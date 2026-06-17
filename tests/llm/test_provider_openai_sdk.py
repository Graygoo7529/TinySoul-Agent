from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from tinysoul.llm.cache import PromptCache
from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
from tinysoul.llm.messages import (
    ImagePart,
    ImageUrlPart,
    Message,
    MessageRole,
    MessageStack,
    TextPart,
)
from tinysoul.llm.models import ModelCapability, ModelSpec, ProviderOptions
from tinysoul.llm.provider import ProviderError, ProviderErrorKind, ProviderRequest
from tinysoul.llm.provider.openai_sdk import (
    OpenAIChatCompletionsAdapter,
    OpenAIResponsesAdapter,
    build_provider_registry,
)
from tinysoul.llm.responses import ResponseContract


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
    adapter = OpenAIResponsesAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_RESPONSES),
        api_key="key",
        responses=client,
    )

    response = adapter.invoke(
        ProviderRequest(
            model=_model(
                provider_id="openai",
                provider_model="gpt-5.5",
                options={"prompt_cache_retention": "24h"},
            ),
            messages=MessageStack.of(
                Message.text(MessageRole.SYSTEM, "system"),
                Message(
                    role=MessageRole.USER,
                    parts=(TextPart("look"), ImagePart(data=b"abc", mime_type="image/png")),
                ),
            ),
            response_contract=ResponseContract.JSON_OBJECT,
            prompt_cache=PromptCache("stable-prefix"),
            temperature=0.2,
            max_output_tokens=256,
            provider_options={"prompt_cache_retention": "24h"},
        )
    )

    call = client.calls[0]
    assert call["model"] == "gpt-5.5"
    assert call["temperature"] == pytest.approx(0.2)
    assert call["max_output_tokens"] == 256
    assert call["prompt_cache_key"] == "stable-prefix"
    assert call["prompt_cache_retention"] == "24h"
    assert call["text"] == {"format": {"type": "json_object"}}
    assert response.text == '{"ok": true}'
    assert response.usage == {"input_tokens": 10, "output_tokens": 3}


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
    adapter = OpenAIChatCompletionsAdapter(
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
            messages=MessageStack.of(Message.text(MessageRole.USER, "hello")),
            response_contract=ResponseContract.JSON_OBJECT,
            prompt_cache=PromptCache("kimi-prefix"),
            max_output_tokens=128,
            provider_options={"thinking": "enabled"},
        )
    )

    call = client.calls[0]
    assert call["model"] == "kimi-k2.7-code"
    assert call["messages"] == [{"role": "user", "content": "hello"}]
    assert call["max_completion_tokens"] == 128
    assert "max_output_tokens" not in call
    assert call["response_format"] == {"type": "json_object"}
    assert call["prompt_cache_key"] == "kimi-prefix"
    assert call["extra_body"] == {"thinking": "enabled"}
    assert response.text == '{"ok": true}'
    assert response.reasoning_text == "thinking"


def test_adapter_skips_native_json_and_cache_when_model_lacks_capability() -> None:
    message = SimpleNamespace(content='{"ok": true}')
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAIChatCompletionsAdapter(
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
            messages=MessageStack.of(Message.text(MessageRole.USER, "hello")),
            response_contract=ResponseContract.JSON_OBJECT,
            prompt_cache=PromptCache("prefix"),
        )
    )

    call = client.calls[0]
    assert "response_format" not in call
    assert "prompt_cache_key" not in call


def test_adapter_maps_remote_image_url_part() -> None:
    message = SimpleNamespace(content="ok")
    client = FakeCreateClient(
        response=SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={},
        )
    )
    adapter = OpenAIChatCompletionsAdapter(
        provider=_provider("openai", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=client,
    )

    adapter.invoke(
        ProviderRequest(
            model=_model(provider_id="openai", provider_model="gpt-5.5"),
            messages=MessageStack.of(
                Message(
                    role=MessageRole.USER,
                    parts=(ImageUrlPart(url="https://example.test/image.png"),),
                )
            ),
            response_contract=ResponseContract.TEXT,
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


def test_provider_option_rejects_unknown_key() -> None:
    adapter = OpenAIChatCompletionsAdapter(
        provider=_provider("kimi", ProviderApiStyle.OPENAI_CHAT),
        api_key="key",
        completions=FakeCreateClient(response=object()),
    )

    with pytest.raises(ProviderError) as exc:
        adapter.invoke(
            ProviderRequest(
                model=_model(provider_id="kimi", provider_model="kimi-k2.7-code"),
                messages=MessageStack.of(Message.text(MessageRole.USER, "hello")),
                response_contract=ResponseContract.TEXT,
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
