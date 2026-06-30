from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from tinysoul.infra.json import JsonObject
from tinysoul.llm.cache import PromptCache
from tinysoul.llm.messages import ImagePart, ImageUrlPart, MessageStack, UserMessage
from tinysoul.llm.model_chain import (
    Clock,
    ModelChain,
    ModelChainState,
    RetryPolicy,
    TaskSpec,
    TaskSpecTable,
)
from tinysoul.llm.models import ModelCapability, ModelRegistry, ModelSpec, ProviderOptions
from tinysoul.llm.provider import ProviderError, ProviderErrorKind, ProviderRequest
from tinysoul.llm.provider.registry import ProviderRegistry
from tinysoul.llm.requests import CallSettings, TaskCall
from tinysoul.llm.responses import (
    JsonAnswer,
    RawResponse,
    AnswerFormat,
    TaskResultStatus,
    TaskResult,
)
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.llm.task import (
    LLMTaskRunner,
)
from tinysoul.runtime.exception import (
    RUNTIME_TURN_END,
    RuntimeException,
)
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
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.JSON_OBJECT_OUTPUT,
            }
        ),
        provider_options=ProviderOptions({"thinking": "enabled"}),
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
    assert request.provider_options == {"thinking": "enabled"}


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


def test_contract_failure_becomes_runtime_unhandled_failure() -> None:
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


def _tasks(chain: ModelChain) -> TaskSpecTable:
    return TaskSpecTable(
        [
            TaskSpec(
                profile=chain.profile,
                chain=chain,
                settings=CallSettings(
                    answer_format=AnswerFormat.JSON_OBJECT,
                    tool_use=ToolUse.DISABLED,
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


