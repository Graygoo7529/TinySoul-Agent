from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from tinysoul.llm.errors import LLMContractError, LLMInvariantError
from tinysoul.llm.cache import PromptCache
from tinysoul.llm.config import ProviderApiStyle, ProviderSpec
from tinysoul.llm.messages import MessageStack, UserMessage
from tinysoul.llm.model_chain import ModelChain, TaskSpec
from tinysoul.llm.models import (
    ModelCapability,
    ModelRegistry,
    ModelSpec,
    ProviderOptions,
)
from tinysoul.llm.provider import ProviderRequest
from tinysoul.llm.provider.registry import ProviderRegistry
from tinysoul.llm.reasoning import ReasoningKeep
from tinysoul.llm.requests import CallSettings, TaskCall
from tinysoul.llm.responses import AnswerFormat, RawResponse
from tinysoul.llm.tools import ToolCallRecord, ToolUse


def test_provider_options_reports_contract_errors() -> None:
    with pytest.raises(LLMContractError):
        ProviderOptions({"reasoning_keep": "forever"}).reasoning_keep()

    with pytest.raises(LLMContractError):
        ProviderOptions({"reasoning_keep": 1}).reasoning_keep()

    with pytest.raises(LLMContractError):
        ProviderOptions({"request_overrides": "bad"}).request_overrides()

    with pytest.raises(LLMContractError):
        ProviderOptions(
            {"request_overrides": {"temperature": True}}
        ).request_overrides()


def test_provider_options_accepts_valid_reasoning_keep() -> None:
    assert (
        ProviderOptions({"reasoning_keep": "encrypted"}).reasoning_keep()
        is ReasoningKeep.ENCRYPTED
    )


def test_provider_options_rejects_non_string_keys() -> None:
    with pytest.raises(LLMContractError):
        ProviderOptions(cast(dict[str, object], {1: "bad"}))


def test_model_spec_rejects_invalid_identity_and_capabilities() -> None:
    with pytest.raises(LLMContractError):
        ModelSpec(id="", provider_id="fake", provider_model="model")

    with pytest.raises(LLMContractError):
        ModelSpec(
            id="model",
            provider_id="fake",
            provider_model="model",
            capabilities=cast(frozenset[ModelCapability], frozenset({"text_input"})),
        )


def test_provider_spec_rejects_invalid_identity_and_key_envs() -> None:
    with pytest.raises(LLMContractError):
        ProviderSpec(
            id="",
            api_style=ProviderApiStyle.OPENAI_CHAT,
            base_url="https://example.test/v1",
            api_key_envs=("API_KEY",),
        )

    with pytest.raises(LLMContractError):
        ProviderSpec(
            id="fake",
            api_style=ProviderApiStyle.OPENAI_CHAT,
            base_url="https://example.test/v1",
            api_key_envs=(),
        )


def test_raw_response_rejects_invalid_identity_and_tool_calls() -> None:
    with pytest.raises(LLMContractError):
        RawResponse(answer_text="ok", model_id="", provider_id="fake")

    with pytest.raises(LLMContractError):
        RawResponse(
            answer_text="ok",
            model_id="model",
            provider_id="fake",
            tool_calls=cast(tuple[ToolCallRecord, ...], (object(),)),
        )


def test_model_registry_uses_llm_errors() -> None:
    model = _model("model_a")
    registry = ModelRegistry([model])

    with pytest.raises(LLMInvariantError):
        registry.register(model)

    with pytest.raises(LLMContractError):
        registry.get("missing")


def test_provider_registry_uses_llm_errors() -> None:
    provider = FakeProvider(provider_id="fake")
    registry = ProviderRegistry([provider])

    with pytest.raises(LLMInvariantError):
        registry.register(provider)

    with pytest.raises(LLMContractError):
        registry.get("missing")


def test_llm_request_models_validate_direct_construction() -> None:
    messages = MessageStack.of(UserMessage.from_text("hello"))
    model = _model("model_a")

    with pytest.raises(LLMContractError, match="max_output_tokens"):
        CallSettings(max_output_tokens=0)
    with pytest.raises(LLMContractError, match="profile"):
        TaskCall(profile="", messages=messages)
    with pytest.raises(LLMContractError, match="PromptCache.key"):
        PromptCache("")
    with pytest.raises(LLMContractError, match="must match"):
        TaskSpec(
            profile="framework",
            chain=ModelChain(profile="other", model_ids=(model.id,)),
        )
    with pytest.raises(LLMContractError, match="max_output_tokens"):
        ProviderRequest(
            model=model,
            messages=messages,
            answer_format=AnswerFormat.TEXT,
            tool_use=ToolUse.DISABLED,
            max_output_tokens=0,
        )


@dataclass
class FakeProvider:
    provider_id: str

    def invoke(self, request: ProviderRequest) -> RawResponse:
        return RawResponse(
            answer_text="ok",
            model_id=request.model.id,
            provider_id=self.provider_id,
        )


def _model(model_id: str) -> ModelSpec:
    return ModelSpec(
        id=model_id,
        provider_id="fake",
        provider_model=model_id,
    )
