from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from tinysoul.llm.cache import PromptCache
from tinysoul.llm.messages import ImagePart, Message, MessageRole, MessageStack
from tinysoul.llm.model_chain import (
    Clock,
    ModelChain,
    ModelChainState,
    ModelChainTable,
    RetryPolicy,
)
from tinysoul.llm.models import ModelCapability, ModelRegistry, ModelSpec
from tinysoul.llm.provider import ProviderError, ProviderErrorKind, ProviderRequest
from tinysoul.llm.provider.registry import ProviderRegistry
from tinysoul.llm.responses import ModelResponse, ResponseContract
from tinysoul.llm.task import LLMTaskError, LLMTaskRunner, ModelCapabilityError, TaskCall


@dataclass
class FakeProvider:
    provider_id: str
    failures: dict[str, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def invoke(self, request: ProviderRequest) -> ModelResponse:
        model_id = request.model.id
        self.calls.append(model_id)
        remaining = self.failures.get(model_id, 0)
        if remaining > 0:
            self.failures[model_id] = remaining - 1
            raise ProviderError("temporary failure", kind=ProviderErrorKind.TRANSIENT)
        return ModelResponse(
            text='{"model": "' + model_id + '"}',
            model_id=model_id,
            provider_id=self.provider_id,
        )


@dataclass
class FakeClock(Clock):
    current: float = 0.0

    def now(self) -> float:
        return self.current


def test_runner_uses_current_model_then_continues_forward_after_failure() -> None:
    provider = FakeProvider(provider_id="fake", failures={"b": 1})
    chain = ModelChain(
        profile="framework.default",
        model_ids=("a", "b", "c"),
        retry_policy=RetryPolicy(
            max_retries_per_model=1,
            max_cycles=1,
        ),
    )
    chain_state = ModelChainState()
    chain_state.mark_success(chain, "b", now=0.0)
    runner = LLMTaskRunner(
        models=_models("a", "b", "c"),
        providers=ProviderRegistry([provider]),
        chains=ModelChainTable([chain]),
        chain_state=chain_state,
    )
    call = TaskCall(
        profile="framework.default",
        messages=MessageStack.of(Message.text(MessageRole.USER, "hello")),
        response_contract=ResponseContract.JSON_OBJECT,
    )

    result = runner.run(call)

    assert result.json_object == {"model": "c"}
    assert provider.calls == ["b", "c"]


def test_runner_exhausts_after_configured_full_chain_cycles() -> None:
    provider = FakeProvider(
        provider_id="fake",
        failures={"a": 2, "b": 2, "c": 2},
    )
    runner = LLMTaskRunner(
        models=_models("a", "b", "c"),
        providers=ProviderRegistry([provider]),
        chains=ModelChainTable(
            [
                ModelChain(
                    profile="framework.default",
                    model_ids=("a", "b", "c"),
                    retry_policy=RetryPolicy(
                        max_retries_per_model=1,
                        max_cycles=2,
                    ),
                )
            ]
        ),
    )

    with pytest.raises(LLMTaskError):
        runner.run(
            TaskCall(
                profile="framework.default",
                messages=MessageStack.of(Message.text(MessageRole.USER, "hello")),
            )
        )

    assert provider.calls == ["a", "b", "c", "a", "b", "c"]


def test_runner_returns_to_chain_head_after_success_preference_expires() -> None:
    provider = FakeProvider(provider_id="fake", failures={"a": 1, "b": 1})
    clock = FakeClock()
    chain = ModelChain(
        profile="framework.default",
        model_ids=("a", "b", "c"),
        retry_policy=RetryPolicy(
            max_retries_per_model=1,
            max_cycles=1,
            prefer_successful_model_seconds=5.0,
        ),
    )
    runner = LLMTaskRunner(
        models=_models("a", "b", "c"),
        providers=ProviderRegistry([provider]),
        chains=ModelChainTable([chain]),
        clock=clock,
    )
    call = TaskCall(
        profile="framework.default",
        messages=MessageStack.of(Message.text(MessageRole.USER, "hello")),
    )

    first = runner.run(call)
    clock.current = 4.0
    second = runner.run(call)
    clock.current = 6.0
    third = runner.run(call)

    assert first.json_object == {"model": "c"}
    assert second.json_object == {"model": "c"}
    assert third.json_object == {"model": "a"}
    assert provider.calls == ["a", "b", "c", "c", "a"]


def test_runner_retries_transient_error_on_same_model() -> None:
    provider = FakeProvider(provider_id="fake", failures={"a": 1})
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        chains=ModelChainTable(
            [
                ModelChain(
                    profile="framework.default",
                    model_ids=("a",),
                    retry_policy=RetryPolicy(max_retries_per_model=2, max_cycles=1),
                )
            ]
        ),
    )

    result = runner.run(
        TaskCall(
            profile="framework.default",
            messages=MessageStack.of(Message.text(MessageRole.USER, "hello")),
        )
    )

    assert result.json_object == {"model": "a"}
    assert provider.calls == ["a", "a"]


def test_retry_policy_defaults_to_ten_cycles() -> None:
    assert RetryPolicy().max_cycles == 10


def test_prompt_cache_intent_does_not_require_model_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        chains=ModelChainTable([ModelChain(profile="framework.default", model_ids=("a",))]),
    )

    result = runner.run(
        TaskCall(
            profile="framework.default",
            messages=MessageStack.of(Message.text(MessageRole.USER, "hello")),
            prompt_cache=PromptCache(key="framework.default:test"),
        )
    )

    assert result.json_object == {"model": "a"}


def test_runner_rejects_missing_image_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        chains=ModelChainTable([ModelChain(profile="framework.default", model_ids=("a",))]),
    )
    stack = MessageStack.of(
        Message(
            role=MessageRole.USER,
            parts=(ImagePart(url="https://example.test/image.png"),),
        )
    )

    with pytest.raises(ModelCapabilityError):
        runner.run(TaskCall(profile="framework.default", messages=stack))


def _models(*ids: str) -> ModelRegistry:
    capabilities = frozenset(
        {
            ModelCapability.TEXT_INPUT,
            ModelCapability.JSON_OBJECT_OUTPUT,
        }
    )
    return ModelRegistry(
        [
            ModelSpec(
                id=model_id,
                provider_id="fake",
                provider_model=model_id,
                capabilities=capabilities,
            )
            for model_id in ids
        ]
    )
