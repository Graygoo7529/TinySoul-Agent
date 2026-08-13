from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.llm.cache import PromptCache
from tinysoul.llm.context_window import RequestTokenEstimate
from tinysoul.llm.messages import ImagePart, ImageUrlPart, MessageStack, UserMessage
from tinysoul.llm.model_chain import (
    Clock,
    ModelChain,
    ModelChainState,
    RetryPolicy,
    TaskSpec,
    TaskSpecTable,
)
from tinysoul.llm.models import (
    AdapterOptions,
    ModelCapability,
    ModelRegistry,
    ModelSpec,
    RequestOverrides,
)
from tinysoul.llm.adapter_types import AdapterKind
from tinysoul.llm.provider import ProviderError, ProviderErrorKind, ProviderRequest
from tinysoul.llm.provider.registry import ProviderRegistry
from tinysoul.llm.requests import (
    CallSettings,
    ModelContextOverflowPolicy,
    TaskCall,
    TaskCancellation,
)
from tinysoul.llm.responses import (
    JsonAnswer,
    RawResponse,
    ResponseStopReason,
    AnswerFormat,
    TaskFailureReason,
    TaskFailureScope,
    TaskResultStatus,
    TaskResult,
)
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.llm.errors import TaskCancelled
from tinysoul.llm.task import (
    LLMTaskRunner,
)
from tinysoul.runtime.exception import (
    CONTEXT_COMPRESSION_REQUIRED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from tinysoul.runtime import ObservationEvent, ObservationLevel
from tinysoul.llm.tools import (
    ToolCallRecord,
    ToolKind,
    ToolScope,
    ToolSelection,
    ToolSpec,
    ToolUse,
)


@dataclass
class FakeProvider:
    provider_id: str
    adapter_kind: AdapterKind = AdapterKind.GENERIC
    failures: dict[str, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    requests: list[ProviderRequest] = field(default_factory=list)

    def invoke(self, request: ProviderRequest) -> RawResponse:
        model_id = request.model.id
        self.calls.append(model_id)
        self.requests.append(request)
        remaining = self.failures.get(model_id, 0)
        if remaining > 0:
            self.failures[model_id] = remaining - 1
            raise ProviderError("temporary failure", kind=ProviderErrorKind.TRANSIENT)
        return RawResponse(
            answer_text='{"model": "' + model_id + '"}',
            model_id=model_id,
            provider_id=self.provider_id,
        )


@dataclass
class FakeClock(Clock):
    current: float = 0.0

    def now(self) -> float:
        return self.current


@dataclass
class RecordingObservations:
    events: list[ObservationEvent] = field(default_factory=list)

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)


def test_runner_observations_share_stable_task_id() -> None:
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

    runner.run(call)

    names = [event.name for event in observations.events]
    assert names[0] == "llm.task.started"
    assert "llm.model.request" in names
    assert names[-1] == "llm.task.completed"
    assert all(
        event.payload["task_id"] == "task_visible"
        for event in observations.events
    )


def test_runner_passes_action_remaining_timeout_to_provider_request() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )
    runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
            cancellation=TaskCancellation(
                cancelled=lambda: False,
                remaining_seconds=lambda: 12.5,
                reason=lambda: "",
            ),
        )
    )

    assert provider.requests[0].timeout_seconds == pytest.approx(12.5)


def test_runner_stops_retry_chain_after_owner_cancellation() -> None:
    state = {"cancelled": False}

    @dataclass
    class CancellingProvider(FakeProvider):
        def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            state["cancelled"] = True
            raise ProviderError("temporary failure", kind=ProviderErrorKind.TRANSIENT)

    provider = CancellingProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b"),
                retry_policy=RetryPolicy(
                    max_retries_per_model=2,
                    max_cycles=10,
                ),
            )
        ),
    )

    with pytest.raises(TaskCancelled, match="timeout"):
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                cancellation=TaskCancellation(
                    cancelled=lambda: state["cancelled"],
                    remaining_seconds=lambda: 10.0,
                    reason=lambda: "timeout",
                ),
            )
        )

    assert provider.calls == ["a"]


@dataclass
class FixedTokenEstimator:
    message_tokens: int
    non_message_tokens: int = 0
    message_chars: int = 100

    def estimate(self, messages: MessageStack, tool_scope: ToolScope) -> RequestTokenEstimate:
        return RequestTokenEstimate(
            message_tokens=self.message_tokens,
            non_message_tokens=self.non_message_tokens,
            message_chars=self.message_chars,
        )


def test_context_hard_water_requests_runtime_recomposition_before_provider() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_window_models(("small", 100)),
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
        token_estimator=FixedTokenEstimator(message_tokens=71),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                context_overflow_policy=(
                    ModelContextOverflowPolicy.RECOMPOSE_CONTEXT
                ),
            )
        )

    assert exc_info.value.reason == CONTEXT_COMPRESSION_REQUIRED
    assert (
        exc_info.value.payload["kind"]
        == LLMFailureKind.MODEL_CONTEXT_COMPRESSION_REQUIRED
    )
    assert exc_info.value.payload["used_tokens"] == 81
    assert exc_info.value.payload["trigger_tokens"] == 80
    assert provider.calls == []


def test_context_hard_water_ends_non_context_task() -> None:
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
        runner.run(
            TaskCall(
                profile="home_search",
                messages=MessageStack.of(UserMessage.from_text("hello")),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CONTEXT_LIMIT_REACHED
    assert provider.calls == []


def test_hard_water_allows_usage_equal_to_trigger() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_window_models(("small", 100)),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(profile="framework", model_ids=("small",)),
            max_output_tokens=10,
        ),
        context_trigger_ratio=0.8,
        token_estimator=FixedTokenEstimator(message_tokens=70),
    )

    result = runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert _json_output(result) == {"model": "small"}
    assert provider.calls == ["small"]


def test_smaller_fallback_requests_recomposition_without_chain_checkpoint() -> None:
    @dataclass
    class LargeFailingProvider(FakeProvider):
        def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            if request.model.id == "large":
                raise ProviderError("unavailable", kind=ProviderErrorKind.CONFIG)
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
        token_estimator=estimator,
    )
    call = TaskCall(
        profile="framework",
        messages=MessageStack.of(UserMessage.from_text("hello")),
        context_overflow_policy=ModelContextOverflowPolicy.RECOMPOSE_CONTEXT,
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(call)

    assert exc_info.value.reason == CONTEXT_COMPRESSION_REQUIRED
    assert exc_info.value.payload["model_id"] == "small"
    assert provider.calls == ["large"]

    estimator.message_tokens = 20
    result = runner.run(call)

    assert _json_output(result) == {"model": "small"}
    assert provider.calls == ["large", "large", "small"]


def test_provider_context_limit_uses_same_recomposition_path() -> None:
    @dataclass
    class ContextRejectingProvider(FakeProvider):
        def invoke(self, request: ProviderRequest) -> RawResponse:
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
        token_estimator=FixedTokenEstimator(message_tokens=20),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                context_overflow_policy=(
                    ModelContextOverflowPolicy.RECOMPOSE_CONTEXT
                ),
            )
        )

    assert exc_info.value.reason == CONTEXT_COMPRESSION_REQUIRED
    assert exc_info.value.payload["provider_reported_limit"] is True
    assert provider.calls == ["model"]


def test_runner_uses_current_model_then_continues_forward_after_failure() -> None:
    provider = FakeProvider(provider_id="fake", failures={"b": 1})
    chain = ModelChain(
        profile="framework",
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
        tasks=_tasks(chain),
        chain_state=chain_state,
    )
    call = TaskCall(
        profile="framework",
        messages=MessageStack.of(UserMessage.from_text("hello")),
    )

    result = runner.run(call)

    assert _json_output(result) == {"model": "c"}
    assert provider.calls == ["b", "c"]


def test_runner_exhausts_after_configured_full_chain_cycles() -> None:
    provider = FakeProvider(
        provider_id="fake",
        failures={"a": 2, "b": 2, "c": 2},
    )
    runner = LLMTaskRunner(
        models=_models("a", "b", "c"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b", "c"),
                retry_policy=RetryPolicy(
                    max_retries_per_model=1,
                    max_cycles=2,
                ),
            )
        ),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CHAIN_EXHAUSTED
    assert exc_info.value.payload["last_error_type"] == "ProviderError"
    assert exc_info.value.payload["provider_error_kind"] == "transient"
    assert provider.calls == ["a", "b", "c", "a", "b", "c"]


def test_runner_returns_to_chain_head_after_success_preference_expires() -> None:
    provider = FakeProvider(provider_id="fake", failures={"a": 1, "b": 1})
    clock = FakeClock()
    chain = ModelChain(
        profile="framework",
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
        tasks=_tasks(chain),
        clock=clock,
    )
    call = TaskCall(
        profile="framework",
        messages=MessageStack.of(UserMessage.from_text("hello")),
    )

    first = runner.run(call)
    clock.current = 4.0
    second = runner.run(call)
    clock.current = 6.0
    third = runner.run(call)

    assert _json_output(first) == {"model": "c"}
    assert _json_output(second) == {"model": "c"}
    assert _json_output(third) == {"model": "a"}
    assert provider.calls == ["a", "b", "c", "c", "a"]


def test_runner_retries_transient_error_on_same_model() -> None:
    provider = FakeProvider(provider_id="fake", failures={"a": 1})
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a",),
                retry_policy=RetryPolicy(max_retries_per_model=2, max_cycles=1),
            )
        ),
    )

    result = runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert _json_output(result) == {"model": "a"}
    assert provider.calls == ["a", "a"]


def test_runner_switches_model_without_retry_for_non_transient_provider_error() -> None:
    @dataclass
    class ConfigFailingProvider(FakeProvider):
        def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            if request.model.id == "a":
                raise ProviderError("bad provider config", kind=ProviderErrorKind.CONFIG)
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
                retry_policy=RetryPolicy(max_retries_per_model=3, max_cycles=1),
            )
        ),
    )

    result = runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert _json_output(result) == {"model": "b"}
    assert provider.calls == ["a", "b"]


def test_retry_policy_defaults_to_ten_cycles() -> None:
    assert RetryPolicy().max_cycles == 10


def test_runner_reports_chain_head_capabilities_by_default() -> None:
    model = ModelSpec(
        id="vision",
        provider_id="fake",
        provider_model="vision-model",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.IMAGE_INPUT,
            }
        ),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([FakeProvider(provider_id="fake")]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("vision",))),
    )

    capabilities = runner.current_model_capabilities("framework")

    assert capabilities.profile == "framework"
    assert capabilities.model_id == "vision"
    assert capabilities.provider_id == "fake"
    assert capabilities.provider_model == "vision-model"
    assert capabilities.supports(ModelCapability.IMAGE_INPUT)
    assert not capabilities.supports(ModelCapability.IMAGE_REMOTE_URL)


def test_runner_reports_successful_fallback_model_during_preference_window() -> None:
    provider = FakeProvider(provider_id="fake", failures={"a": 1})
    clock = FakeClock()
    chain = ModelChain(
        profile="framework",
        model_ids=("a", "b"),
        retry_policy=RetryPolicy(
            max_retries_per_model=1,
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

    runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert runner.current_model_capabilities("framework").model_id == "b"


def test_runner_capability_query_returns_to_head_after_preference_expires() -> None:
    provider = FakeProvider(provider_id="fake", failures={"a": 1})
    clock = FakeClock()
    chain = ModelChain(
        profile="framework",
        model_ids=("a", "b"),
        retry_policy=RetryPolicy(
            max_retries_per_model=1,
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

    runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )
    clock.current = 6.0

    assert runner.current_model_capabilities("framework").model_id == "a"


def test_prompt_cache_intent_does_not_require_model_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    result = runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
            prompt_cache=PromptCache(key="framework:test"),
        )
    )

    assert _json_output(result) == {"model": "a"}


def test_json_object_contract_does_not_require_native_json_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="a",
        provider_id="fake",
        provider_model="a",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset({ModelCapability.TEXT_INPUT}),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    result = runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert _json_output(result) == {"model": "a"}


def test_runner_rejects_missing_image_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )
    stack = MessageStack.of(
        UserMessage.from_parts(ImagePart(data=b"abc", mime_type="image/png"))
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(TaskCall(profile="framework", messages=stack))

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CHAIN_EXHAUSTED
    assert exc_info.value.payload["last_error_type"] == "ModelCapabilityError"
    assert exc_info.value.payload["missing_capabilities"] == ["image_input"]


def test_runner_skips_model_missing_call_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    text_model = ModelSpec(
        id="text",
        provider_id="fake",
        provider_model="text",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset({ModelCapability.TEXT_INPUT}),
    )
    vision_model = ModelSpec(
        id="vision",
        provider_id="fake",
        provider_model="vision",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.IMAGE_INPUT,
                ModelCapability.JSON_OBJECT_OUTPUT,
            }
        ),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([text_model, vision_model]),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("text", "vision"))),
    )
    stack = MessageStack.of(
        UserMessage.from_parts(ImagePart(data=b"abc", mime_type="image/png"))
    )

    result = runner.run(TaskCall(profile="framework", messages=stack))

    assert _json_output(result) == {"model": "vision"}
    assert provider.calls == ["vision"]


def test_runner_rejects_missing_remote_image_url_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )
    stack = MessageStack.of(
        UserMessage.from_parts(ImageUrlPart(url="https://example.test/image.png"))
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(TaskCall(profile="framework", messages=stack))

    assert exc_info.value.reason == RUNTIME_TURN_END


def test_call_settings_can_add_required_capabilities() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                settings=CallSettings(
                    required_capabilities=frozenset(
                        {ModelCapability.IMAGE_REMOTE_URL}
                    )
                ),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END


def test_runner_resolves_task_settings_and_call_overrides() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="a",
        provider_id="fake",
        provider_model="a",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.JSON_OBJECT_OUTPUT,
            }
        ),
        adapter_options=AdapterOptions({"thinking": "enabled"}),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([provider]),
        tasks=TaskSpecTable(
            [
                TaskSpec(
                    profile="framework",
                    chain=ModelChain(profile="framework", model_ids=("a",)),
                    settings=CallSettings(
                        answer_format=AnswerFormat.JSON_OBJECT,
                        tool_use=ToolUse.DISABLED,
                        temperature=0.6,
                        max_output_tokens=4096,
                    ),
                )
            ]
        ),
    )

    runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
            settings=CallSettings(max_output_tokens=1024),
        )
    )

    request = provider.requests[0]
    assert request.temperature == pytest.approx(0.6)
    assert request.max_output_tokens == 1024
    assert request.model.adapter_options.values == {"thinking": "enabled"}


def test_runner_applies_model_request_overrides_after_call_settings() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="a",
        provider_id="fake",
        provider_model="a",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.JSON_OBJECT_OUTPUT,
            }
        ),
        request_overrides=RequestOverrides(
            temperature=1.0,
            max_output_tokens=128,
        ),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([provider]),
        tasks=TaskSpecTable(
            [
                TaskSpec(
                    profile="framework",
                    chain=ModelChain(profile="framework", model_ids=("a",)),
                    settings=CallSettings(
                        answer_format=AnswerFormat.JSON_OBJECT,
                        tool_use=ToolUse.DISABLED,
                        temperature=0.6,
                        max_output_tokens=4096,
                    ),
                )
            ]
        ),
    )

    runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
            settings=CallSettings(temperature=0.2, max_output_tokens=1024),
        )
    )

    request = provider.requests[0]
    assert request.temperature == pytest.approx(1.0)
    assert request.max_output_tokens == 128


def test_runner_rejects_tool_task_without_tool_calling_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                tool_scope=ToolScope(tools=(_tool(),)),
                settings=CallSettings(
                    answer_format=AnswerFormat.NONE,
                    tool_use=ToolUse.REQUIRED,
                ),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END


def test_runner_rejects_tool_scope_when_tool_use_is_disabled() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="tool_model",
        provider_id="fake",
        provider_model="tool-model",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TOOL_CALLING,
            }
        ),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("tool_model",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                tool_scope=ToolScope(tools=(_tool(),)),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END


def test_runner_rejects_enabled_tool_use_without_visible_tools() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="tool_model",
        provider_id="fake",
        provider_model="tool-model",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TOOL_CALLING,
            }
        ),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([provider]),
        tasks=TaskSpecTable(
            [
                TaskSpec(
                    profile="framework",
                    chain=ModelChain(profile="framework", model_ids=("tool_model",)),
                    settings=CallSettings(
                        answer_format=AnswerFormat.NONE,
                        tool_use=ToolUse.REQUIRED,
                    ),
                )
            ]
        ),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END


def test_runner_rejects_forced_tool_selection_without_required_tool_use() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="tool_model",
        provider_id="fake",
        provider_model="tool-model",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TOOL_CALLING,
            }
        ),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([provider]),
        tasks=TaskSpecTable(
            [
                TaskSpec(
                    profile="framework",
                    chain=ModelChain(profile="framework", model_ids=("tool_model",)),
                    settings=CallSettings(
                        answer_format=AnswerFormat.NONE,
                        tool_use=ToolUse.OPTIONAL,
                    ),
                )
            ]
        ),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                tool_scope=ToolScope(
                    tools=(_tool(),),
                    selection=ToolSelection(forced_name="read_file"),
                ),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END


def test_runner_interprets_tool_call_output() -> None:
    tool_call = ToolCallRecord(
        id="call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
        kind=ToolKind.ACTION,
    )

    @dataclass
    class ToolProvider(FakeProvider):
        def invoke(self, request: ProviderRequest) -> RawResponse:
            self.requests.append(request)
            return RawResponse(
                answer_text="",
                model_id=request.model.id,
                provider_id=self.provider_id,
                tool_calls=(tool_call,),
            )

    model = ModelSpec(
        id="tool_model",
        provider_id="fake",
        provider_model="tool-model",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TOOL_CALLING,
            }
        ),
    )
    provider = ToolProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([provider]),
        tasks=TaskSpecTable(
            [
                TaskSpec(
                    profile="framework",
                    chain=ModelChain(profile="framework", model_ids=("tool_model",)),
                    settings=CallSettings(
                        answer_format=AnswerFormat.NONE,
                        tool_use=ToolUse.REQUIRED,
                    ),
                )
            ]
        ),
    )

    result = runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
            tool_scope=ToolScope(tools=(_tool(),)),
        )
    )

    assert result.answer is None
    assert result.tool_calls == (tool_call,)
    assert provider.requests[0].tool_scope.tools == (_tool(),)


def test_runner_returns_failure_result_for_json_parse_error() -> None:
    class BadJsonProvider(FakeProvider):
        def invoke(self, request: ProviderRequest) -> RawResponse:
            self.requests.append(request)
            return RawResponse(
                answer_text="{bad json",
                model_id=request.model.id,
                provider_id=self.provider_id,
            )

    provider = BadJsonProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    result = runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert result.status is TaskResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.model_feedback is not None
    assert "Failed to parse model response as JSON object" in result.failure.model_feedback


def test_runner_reports_output_limit_before_interpreting_partial_json() -> None:
    class TruncatedProvider(FakeProvider):
        def invoke(self, request: ProviderRequest) -> RawResponse:
            self.requests.append(request)
            return RawResponse(
                answer_text='{"text":"partial',
                model_id=request.model.id,
                provider_id=self.provider_id,
                stop_reason=ResponseStopReason.OUTPUT_LIMIT,
            )

    provider = TruncatedProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(profile="framework", model_ids=("a",)),
            max_output_tokens=2048,
        ),
    )

    result = runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("write")),
        )
    )

    assert result.status is TaskResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.reason is TaskFailureReason.OUTPUT_LIMIT_REACHED
    assert result.failure.scope is TaskFailureScope.OUTPUT
    assert result.failure.constraint == {"max_output_tokens": 2048}
    assert result.failure.frame_data == {}


def test_model_chain_exhaustion_becomes_runtime_reason() -> None:
    provider = FakeProvider(
        provider_id="fake",
        failures={"a": 2, "b": 2},
    )
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b"),
                retry_policy=RetryPolicy(
                    max_retries_per_model=1,
                    max_cycles=1,
                ),
            )
        ),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CHAIN_EXHAUSTED
    assert exc_info.value.payload["last_error_type"] == "ProviderError"
    assert exc_info.value.payload["provider_error_kind"] == "transient"


def test_model_chain_exhaustion_payload_reports_non_transient_provider_error() -> None:
    @dataclass
    class ConfigFailingProvider(FakeProvider):
        def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            raise ProviderError("bad provider config", kind=ProviderErrorKind.CONFIG)

    provider = ConfigFailingProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b"),
                retry_policy=RetryPolicy(
                    max_retries_per_model=3,
                    max_cycles=10,
                ),
            )
        ),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CHAIN_EXHAUSTED
    assert exc_info.value.payload["last_error_type"] == "ProviderError"
    assert exc_info.value.payload["provider_error_kind"] == "config"
    assert provider.calls == ["a", "b"]


def test_programming_error_aborts_chain_without_switching_models() -> None:
    @dataclass
    class BuggyProvider(FakeProvider):
        def invoke(self, request: ProviderRequest) -> RawResponse:
            self.calls.append(request.model.id)
            raise RuntimeError("programming error")

    provider = BuggyProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a", "b"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(
                profile="framework",
                model_ids=("a", "b"),
                retry_policy=RetryPolicy(max_retries_per_model=3, max_cycles=10),
            )
        ),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
            )
        )

    assert exc_info.value.payload["kind"] == LLMFailureKind.INTERNAL_FAILURE
    assert provider.calls == ["a"]


def test_contract_failure_maps_to_runtime_turn_end() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                tool_scope=ToolScope(tools=(_tool(),)),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.CONTRACT_VIOLATION


def test_runner_reports_unknown_model_as_contract_violation() -> None:
    runner = LLMTaskRunner(
        models=ModelRegistry([]),
        providers=ProviderRegistry([FakeProvider(provider_id="fake")]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("missing",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.CONTRACT_VIOLATION


def test_runner_reports_unknown_provider_as_contract_violation() -> None:
    model = ModelSpec(
        id="model_a",
        provider_id="missing",
        provider_model="model-a",
        context_window_tokens=262_144,
        adapter=AdapterKind.GENERIC,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.JSON_OBJECT_OUTPUT,
            }
        ),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("model_a",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.CONTRACT_VIOLATION


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
                context_window_tokens=262_144,
                adapter=AdapterKind.GENERIC,
                capabilities=capabilities,
            )
            for model_id in ids
        ]
    )


def _window_models(*items: tuple[str, int]) -> ModelRegistry:
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
                context_window_tokens=window,
                adapter=AdapterKind.GENERIC,
                capabilities=capabilities,
            )
            for model_id, window in items
        ]
    )


def _tasks(
    chain: ModelChain,
    *,
    max_output_tokens: int | None = None,
) -> TaskSpecTable:
    return TaskSpecTable(
        [
            TaskSpec(
                profile=chain.profile,
                chain=chain,
                settings=CallSettings(
                    answer_format=AnswerFormat.JSON_OBJECT,
                    tool_use=ToolUse.DISABLED,
                    max_output_tokens=max_output_tokens,
                ),
            )
        ]
    )


def _tool() -> ToolSpec:
    return ToolSpec(
        name="read_file",
        description="Read a workspace file",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        kind=ToolKind.ACTION,
    )


def _json_output(result: TaskResult) -> JsonObject:
    if not isinstance(result.answer, JsonAnswer):
        raise AssertionError("Expected JSON answer")
    return result.answer.value
