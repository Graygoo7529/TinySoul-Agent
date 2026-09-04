from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from tinysoul.llm.adapter_types import AdapterKind
from tinysoul.llm.adapter import adapter_spec
from tinysoul.llm.errors import LLMContractError, LLMInvariantError
from tinysoul.llm.messages import MessageStack, UserMessage
from tinysoul.llm.models import (
    ModelCapability,
    ModelProviderBinding,
    ModelRegistry,
    ModelSpec,
)
from tinysoul.llm.provider import ProviderRequest
from tinysoul.llm.provider.registry import ProviderRegistry
from tinysoul.llm.reasoning import ReasoningKeep
from tinysoul.llm.models import AdapterOptions, RequestOverrides
from tinysoul.llm.responses import AnswerFormat, RawResponse
from tinysoul.llm.tools import ToolCallRecord, ToolUse


def test_adapter_options_contract_and_reasoning_keep() -> None:
    with pytest.raises(LLMContractError):
        AdapterOptions({"reasoning_keep": "forever"}).reasoning_keep()
    assert AdapterOptions({"reasoning_keep": "encrypted"}).reasoning_keep() is ReasoningKeep.ENCRYPTED


def test_request_overrides_reject_invalid_values() -> None:
    with pytest.raises(LLMContractError):
        RequestOverrides(temperature=True)
    with pytest.raises(LLMContractError):
        RequestOverrides(max_output_tokens=0)


def test_model_spec_rejects_invalid_identity_capabilities_and_provider_chain() -> None:
    with pytest.raises(LLMContractError):
        ModelSpec(id="", providers=(ModelProviderBinding("fake", "model"),), context_window_tokens=262_144, adapter=AdapterKind.OPENAI_COMPATIBLE_CHAT)
    with pytest.raises(LLMContractError):
        ModelSpec(id="model", providers=(ModelProviderBinding("fake", "model"),), context_window_tokens=0, adapter=AdapterKind.OPENAI_COMPATIBLE_CHAT)
    with pytest.raises(LLMContractError):
        ModelSpec(id="model", providers=(ModelProviderBinding("fake", "one"), ModelProviderBinding("fake", "two")), context_window_tokens=262_144, adapter=AdapterKind.OPENAI_COMPATIBLE_CHAT)


def test_provider_spec_rejects_empty_or_duplicate_adapters() -> None:
    from tinysoul.llm.config_types import ProviderSpec

    with pytest.raises(LLMContractError):
        ProviderSpec(id="fake", adapters=(), base_url="https://example.test/v1", api_key_envs=("API_KEY",))
    with pytest.raises(LLMContractError):
        ProviderSpec(id="fake", adapters=(AdapterKind.OPENAI_COMPATIBLE_CHAT, AdapterKind.OPENAI_COMPATIBLE_CHAT), base_url="https://example.test/v1", api_key_envs=("API_KEY",))


def test_raw_response_rejects_invalid_identity_and_tool_calls() -> None:
    with pytest.raises(LLMContractError):
        RawResponse(answer_text="ok", model_id="", provider_id="fake")
    with pytest.raises(LLMContractError):
        RawResponse(answer_text="ok", model_id="model", provider_id="fake", tool_calls=cast(tuple[ToolCallRecord, ...], (object(),)))


def test_registries_use_llm_errors_and_compound_provider_key() -> None:
    model = _model("model_a")
    models = ModelRegistry([model])
    with pytest.raises(LLMInvariantError):
        models.register(model)
    with pytest.raises(LLMContractError):
        models.get("missing")
    chat = FakeProvider("proxy", AdapterKind.OPENAI_COMPATIBLE_CHAT)
    kimi = FakeProvider("proxy", AdapterKind.KIMI)
    providers = ProviderRegistry([chat, kimi])
    assert providers.get("proxy", AdapterKind.KIMI) is kimi
    with pytest.raises(LLMInvariantError):
        providers.register(kimi)


def test_provider_request_requires_model_binding() -> None:
    model = _model("model_a")
    messages = MessageStack.of(UserMessage.from_text("hello"))
    with pytest.raises(LLMContractError, match="binding"):
        ProviderRequest(model=model, binding=cast(ModelProviderBinding, object()), messages=messages, answer_format=AnswerFormat.TEXT)
    with pytest.raises(LLMContractError, match="max_output_tokens"):
        ProviderRequest(model=model, binding=model.providers[0], messages=messages, answer_format=AnswerFormat.TEXT, max_output_tokens=0)


@dataclass
class FakeProvider:
    provider_id: str
    adapter_kind: AdapterKind = AdapterKind.OPENAI_COMPATIBLE_CHAT

    @property
    def api_style(self):
        return adapter_spec(self.adapter_kind).api_style

    def invoke(self, request: ProviderRequest) -> RawResponse:
        return RawResponse(answer_text="ok", model_id=request.model.id, provider_id=self.provider_id)


def _model(model_id: str) -> ModelSpec:
    return ModelSpec(id=model_id, providers=(ModelProviderBinding("fake", model_id),), context_window_tokens=262_144, adapter=AdapterKind.OPENAI_COMPATIBLE_CHAT)
