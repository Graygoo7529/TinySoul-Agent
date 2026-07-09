from __future__ import annotations

from dataclasses import dataclass

import pytest

from tinysoul.llm.errors import LLMContractError, LLMInvariantError
from tinysoul.llm.models import ModelRegistry, ModelSpec, ProviderOptions
from tinysoul.llm.provider import ProviderRequest
from tinysoul.llm.provider.registry import ProviderRegistry
from tinysoul.llm.reasoning import ReasoningKeep
from tinysoul.llm.responses import RawResponse


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
