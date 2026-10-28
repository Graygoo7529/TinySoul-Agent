from __future__ import annotations
from dataclasses import dataclass
import pytest
from tinysoul.llm.protocol.messages import MessageStack, UserMessage
from tinysoul.llm.protocol.routing import ModelChain, RetryPolicy
from tinysoul.llm.adapter import (
    ProviderError,
    ProviderErrorKind,
    ProviderFailureScope,
    ProviderRequest,
)
from tinysoul.llm.adapter.registry import ProviderRegistry
from tinysoul.llm.protocol.requests import ModelContextOverflowPolicy, TaskCall
from tinysoul.llm.protocol.responses import RawResponse
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.llm.execution.task import LLMTaskRunner
from tinysoul.llm.execution.context_window import ModelContextPolicy
from tinysoul.llm.errors import LLMContractError
from tinysoul.llm.failures import LLM_CONTEXT_CAPACITY_EXCEEDED
from tinysoul.runtime import RUNTIME_TURN_END, RuntimeException
from tests.llm.execution.support import (
    FakeProvider,
    FixedTokenEstimator,
    _json_output,
    _tasks,
    _window_models,
)


def test_direct_window_policy_rejects_nonpositive_limit() -> None:
    with pytest.raises(LLMContractError, match="positive integer"):
        ModelContextPolicy(trigger_ratio=0.8, max_window_tokens=0)


@pytest.mark.parametrize("window, limit", [(100, None), (1000, 100), (100, 1000)])
async def test_context_hard_water_requests_runtime_recomposition_before_provider(
    window: int, limit: int | None,
) -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_window_models(("small", window)),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("small",),
                retry_policy=RetryPolicy(max_cycles=1),
            ),
            max_output_tokens=10,
        ),
        context_trigger_ratio=0.8,
        context_max_window_tokens=limit,
        token_estimator=FixedTokenEstimator(message_tokens=71),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    context_overflow_policy=(
                        ModelContextOverflowPolicy.REQUEST_RECOVERY
                    ),
                )
            )
        )

    assert exc_info.value.reason == LLM_CONTEXT_CAPACITY_EXCEEDED
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CONTEXT_PRESSURE
    assert exc_info.value.payload["used_tokens"] == 81
    assert exc_info.value.payload["effective_window_tokens"] == 100
    assert exc_info.value.payload["trigger_tokens"] == 80
    assert provider.calls == []


async def test_context_hard_water_ends_non_context_task() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_window_models(("small", 100)),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="home_search",
                model_ids=("small",),
                retry_policy=RetryPolicy(max_cycles=1),
            ),
            max_output_tokens=10,
        ),
        context_trigger_ratio=0.8,
        token_estimator=FixedTokenEstimator(message_tokens=71),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
                TaskCall(
                    profile="home_search",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                )
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CONTEXT_LIMIT_REACHED
    assert provider.calls == []


async def test_hard_water_allows_usage_equal_to_trigger() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_window_models(("small", 1000)),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(profile="framework", model_ids=("small",)),
            max_output_tokens=10,
        ),
        context_trigger_ratio=0.8,
        context_max_window_tokens=100,
        token_estimator=FixedTokenEstimator(message_tokens=70),
    )

    result = await runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert _json_output(result) == {"model": "small"}
    assert provider.calls == ["small"]


async def test_smaller_fallback_requests_recomposition_without_chain_checkpoint() -> (
    None
):
    @dataclass
    class LargeFailingProvider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            if request.model.id == "large":
                raise ProviderError(
                    "unavailable",
                    kind=ProviderErrorKind.CONFIG,
                    scope=ProviderFailureScope.PROVIDER,
                )
            return RawResponse(
                answer_text='{"model": "small"}',
                model_id=request.model.id,
                provider_id=self.provider_id,
            )

    provider = LargeFailingProvider(provider_id="fake")
    estimator = FixedTokenEstimator(message_tokens=71)
    runner = LLMTaskRunner(
        models=_window_models(("large", 1000), ("small", 100)),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("large", "small"),
                retry_policy=RetryPolicy(max_cycles=1),
            ),
            max_output_tokens=10,
        ),
        context_trigger_ratio=0.8,
        context_max_window_tokens=500,
        token_estimator=estimator,
    )
    call = TaskCall(
        profile="framework",
        messages=MessageStack.of(UserMessage.from_text("hello")),
        context_overflow_policy=ModelContextOverflowPolicy.REQUEST_RECOVERY,
    )

    with pytest.raises(RuntimeException) as exc_info:
        (await runner.run(call))

    assert exc_info.value.reason == LLM_CONTEXT_CAPACITY_EXCEEDED
    assert exc_info.value.payload["model_id"] == "small"
    assert exc_info.value.payload["effective_window_tokens"] == 100
    assert provider.calls == ["large"]

    estimator.message_tokens = 20
    result = await runner.run(call)

    assert _json_output(result) == {"model": "small"}
    assert provider.calls == ["large", "large", "small"]


async def test_bounded_task_returns_capacity_failure_without_provider_response() -> (
    None
):
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_window_models(("small", 1000)),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(profile="framework", model_ids=("small",)), max_output_tokens=10
        ),
        context_trigger_ratio=0.8,
        context_max_window_tokens=100,
        token_estimator=FixedTokenEstimator(message_tokens=71),
    )
    result = await runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("complete input")),
            context_overflow_policy=ModelContextOverflowPolicy.RETURN_FAILURE,
        )
    )
    assert (
        result.failure is not None and result.failure.reason.value == "input_capacity"
    )
    assert result.raw_response is None and not provider.calls


async def test_provider_context_limit_uses_same_recomposition_path() -> None:
    @dataclass
    class ContextRejectingProvider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            raise ProviderError(
                "provider context limit",
                kind=ProviderErrorKind.CONTEXT_LIMIT,
            )

    provider = ContextRejectingProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_window_models(("model", 1000)),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("model",))),
        context_max_window_tokens=500,
        token_estimator=FixedTokenEstimator(message_tokens=20),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    context_overflow_policy=(
                        ModelContextOverflowPolicy.REQUEST_RECOVERY
                    ),
                )
            )
        )

    assert exc_info.value.reason == LLM_CONTEXT_CAPACITY_EXCEEDED
    assert exc_info.value.payload["provider_reported_limit"] is True
    assert exc_info.value.payload["effective_window_tokens"] == 500
    assert provider.calls == ["model"]
