from __future__ import annotations
from dataclasses import dataclass
import pytest
from tinysoul.llm.protocol.cache import PromptCache
from tinysoul.llm.protocol.messages import MessageStack, UserMessage
from tinysoul.llm.execution.model_chain import LLMRouteState
from tinysoul.llm.protocol.routing import ModelChain, RetryPolicy
from tinysoul.llm.protocol.models import (
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
)
from tinysoul.llm.execution.registry import ModelRegistry
from tinysoul.llm.protocol.adapter_types import AdapterKind
from tinysoul.llm.adapter import (
    ProviderError,
    ProviderErrorKind,
    ProviderFailureScope,
    ProviderRequest,
)
from tinysoul.llm.adapter.registry import ProviderRegistry
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import RawResponse
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.llm.errors import LLMContractError
from tinysoul.llm.execution.task import LLMTaskRunner
from tinysoul.runtime import RUNTIME_TURN_END, RuntimeException
from tests.llm.execution.support import (
    FakeClock,
    FakeProvider,
    RecordingObservations,
    _json_output,
    _models,
    _tasks,
)


async def test_runner_observations_share_stable_task_id() -> None:
    provider = FakeProvider(provider_id="fake")
    observations = RecordingObservations()
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
        observations=observations,
    )
    call = TaskCall(
        profile="framework",
        messages=MessageStack.of(UserMessage.from_text("hello")),
        task_id="task_visible",
    )

    (await runner.run(call))

    names = [event.name for event in observations.events]
    assert names[0] == "llm.task.started"
    assert "llm.model.request" in names
    assert names[-1] == "llm.task.completed"
    assert all(
        event.payload["task_id"] == "task_visible" for event in observations.events
    )


async def test_runner_retries_provider_before_switching_to_next_provider() -> None:
    primary = FakeProvider(provider_id="primary", failures={"shared": 2})
    backup = FakeProvider(provider_id="backup")
    model = ModelSpec(
        id="shared",
        providers=(
            ModelProviderBinding("primary", "primary-model"),
            ModelProviderBinding("backup", "backup-model"),
        ),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
        capabilities=frozenset({ModelCapability.TEXT_INPUT}),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([primary, backup]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("shared",),
                retry_policy=RetryPolicy(max_retries_per_provider=1, max_cycles=1),
            )
        ),
    )

    result = await runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
            prompt_cache=PromptCache(key="2026-10-22/1"),
        )
    )

    assert _json_output(result) == {"model": "shared"}
    assert primary.calls == ["shared", "shared"]
    assert backup.calls == ["shared"]
    assert backup.requests[0].binding.provider_model == "backup-model"
    assert all(
        request.prompt_cache == PromptCache(key="2026-10-22/1")
        for request in (*primary.requests, *backup.requests)
    )


async def test_backup_provider_preference_expires_back_to_chain_head() -> None:
    primary = FakeProvider(provider_id="primary", failures={"shared": 1})
    backup = FakeProvider(provider_id="backup")
    model = ModelSpec(
        id="shared",
        providers=(
            ModelProviderBinding("primary", "primary-model"),
            ModelProviderBinding("backup", "backup-model"),
        ),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
        capabilities=frozenset({ModelCapability.TEXT_INPUT}),
    )
    clock = FakeClock()
    state = LLMRouteState()
    policy = RetryPolicy(
        max_retries_per_provider=0,
        max_cycles=1,
        prefer_successful_provider_seconds=10,
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([primary, backup]),
        tasks=_tasks(
            ModelChain(profile="framework", model_ids=("shared",), retry_policy=policy)
        ),
        route_state=state,
        clock=clock,
    )
    call = TaskCall(
        profile="framework",
        messages=MessageStack.of(UserMessage.from_text("hello")),
    )

    (await runner.run(call))
    assert [request.binding.provider_id for request in backup.requests] == ["backup"]

    clock.current = 1
    (await runner.run(call))
    assert [request.binding.provider_id for request in backup.requests] == [
        "backup",
        "backup",
    ]

    clock.current = 11
    (await runner.run(call))
    assert primary.requests[-1].binding.provider_id == "primary"


async def test_runner_uses_current_model_then_continues_forward_after_failure() -> None:
    provider = FakeProvider(provider_id="fake", failures={"b": 1})
    chain = ModelChain(
        profile="framework",
        model_ids=("a", "b", "c"),
        retry_policy=RetryPolicy(
            max_retries_per_provider=0,
            max_cycles=1,
            prefer_successful_model_seconds=10**20,
        ),
    )
    chain_state = LLMRouteState()
    chain_state.mark_success(chain, "b", now=0.0)
    runner = LLMTaskRunner(
        models=_models("a", "b", "c"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(chain),
        route_state=chain_state,
    )
    call = TaskCall(
        profile="framework",
        messages=MessageStack.of(UserMessage.from_text("hello")),
    )

    result = await runner.run(call)

    assert _json_output(result) == {"model": "c"}
    assert provider.calls == ["b", "c"]


async def test_runner_exhausts_after_configured_full_chain_cycles() -> None:
    provider = FakeProvider(
        provider_id="fake",
        failures={"a": 99, "b": 99, "c": 99},
    )
    runner = LLMTaskRunner(
        models=_models("a", "b", "c"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b", "c"),
                retry_policy=RetryPolicy(
                    max_retries_per_provider=1,
                    max_cycles=2,
                ),
            )
        ),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                )
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CHAIN_EXHAUSTED
    assert exc_info.value.payload["last_error_type"] == "ProviderError"
    assert exc_info.value.payload["provider_error_kind"] == "transient"
    assert provider.calls == [
        "a",
        "a",
        "b",
        "b",
        "c",
        "c",
        "a",
        "a",
        "b",
        "b",
        "c",
        "c",
    ]


async def test_runner_returns_to_chain_head_after_success_preference_expires() -> None:
    provider = FakeProvider(provider_id="fake", failures={"a": 1, "b": 1})
    clock = FakeClock()
    chain = ModelChain(
        profile="framework",
        model_ids=("a", "b", "c"),
        retry_policy=RetryPolicy(
            max_retries_per_provider=0,
            max_cycles=1,
            prefer_successful_model_seconds=5.0,
        ),
    )
    runner = LLMTaskRunner(
        models=_models("a", "b", "c"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(chain),
        clock=clock,
    )
    call = TaskCall(
        profile="framework",
        messages=MessageStack.of(UserMessage.from_text("hello")),
    )

    first = await runner.run(call)
    clock.current = 4.0
    second = await runner.run(call)
    clock.current = 6.0
    third = await runner.run(call)

    assert _json_output(first) == {"model": "c"}
    assert _json_output(second) == {"model": "c"}
    assert _json_output(third) == {"model": "a"}
    assert provider.calls == ["a", "b", "c", "c", "a"]


async def test_runner_retries_transient_error_on_same_model() -> None:
    provider = FakeProvider(provider_id="fake", failures={"a": 1})
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a",),
                retry_policy=RetryPolicy(max_retries_per_provider=2, max_cycles=1),
            )
        ),
    )

    result = await runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert _json_output(result) == {"model": "a"}
    assert provider.calls == ["a", "a"]


async def test_runner_switches_model_without_retry_for_non_transient_provider_error() -> (
    None
):
    @dataclass
    class ConfigFailingProvider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            if request.model.id == "a":
                raise ProviderError(
                    "bad provider config",
                    kind=ProviderErrorKind.CONFIG,
                    scope=ProviderFailureScope.PROVIDER,
                )
            return RawResponse(
                answer_text='{"model": "' + request.model.id + '"}',
                model_id=request.model.id,
                provider_id=self.provider_id,
            )

    provider = ConfigFailingProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b"),
                retry_policy=RetryPolicy(max_retries_per_provider=3, max_cycles=1),
            )
        ),
    )

    result = await runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert _json_output(result) == {"model": "b"}
    assert provider.calls == ["a", "b"]


def test_retry_policy_defaults_to_ten_cycles() -> None:
    assert RetryPolicy().max_cycles == 10


def test_retry_policy_rejects_boolean_retry_count() -> None:
    with pytest.raises(LLMContractError, match="non-negative integer"):
        RetryPolicy(max_retries_per_provider=True)


async def test_runner_skips_models_without_a_registered_provider() -> None:
    unavailable = ModelSpec(
        id="unavailable",
        providers=(ModelProviderBinding("disabled", "remote-a"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
        capabilities=frozenset(
            {ModelCapability.TEXT_INPUT, ModelCapability.JSON_OBJECT_OUTPUT}
        ),
    )
    available = ModelSpec(
        id="available",
        providers=(ModelProviderBinding("fake", "remote-b"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
        capabilities=frozenset(
            {ModelCapability.TEXT_INPUT, ModelCapability.JSON_OBJECT_OUTPUT}
        ),
    )
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=ModelRegistry([unavailable, available]),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("unavailable", "available"),
            )
        ),
    )

    result = await runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert _json_output(result) == {"model": "available"}
    assert provider.calls == ["available"]
    assert runner.current_model_capabilities("framework").model_id == "available"


async def test_runner_reports_successful_fallback_model_during_preference_window() -> (
    None
):
    provider = FakeProvider(provider_id="fake", failures={"a": 1})
    clock = FakeClock()
    chain = ModelChain(
        profile="framework",
        model_ids=("a", "b"),
        retry_policy=RetryPolicy(
            max_retries_per_provider=0,
            max_cycles=1,
            prefer_successful_model_seconds=5.0,
        ),
    )
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(chain),
        clock=clock,
    )

    (
        await runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
            )
        )
    )

    assert runner.current_model_capabilities("framework").model_id == "b"
