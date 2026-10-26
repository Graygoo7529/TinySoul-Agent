from __future__ import annotations
from dataclasses import dataclass, replace
import pytest
from tinysoul.llm.protocol.cache import PromptCache
from tinysoul.llm.protocol.messages import (
    ImagePart,
    ImageUrlPart,
    MessageStack,
    UserMessage,
)
from tinysoul.llm.execution.model_chain import TaskSpecTable
from tinysoul.llm.protocol.routing import ModelChain, RetryPolicy, TaskSpec
from tinysoul.llm.protocol.models import (
    AdapterOptions,
    ModelCapability,
    ModelProviderBinding,
    ModelSpec,
    RequestOverrides,
)
from tinysoul.llm.execution.registry import ModelRegistry
from tinysoul.llm.protocol.adapter_types import AdapterKind
from tinysoul.llm.adapter import ProviderRequest
from tinysoul.llm.adapter.registry import ProviderRegistry
from tinysoul.llm.protocol.requests import CallSettings, TaskCall
from tinysoul.llm.protocol.responses import (
    RawResponse,
    ResponseStopReason,
    AnswerFormat,
    TaskFailureReason,
    TaskFailureScope,
    TaskResultStatus,
)
from tinysoul.llm.failures import LLMFailureKind
from tinysoul.llm.execution.task import LLMTaskRunner
from tinysoul.runtime import RUNTIME_TURN_END, RuntimeException
from tinysoul.llm.protocol.tools import (
    ToolCallRecord,
    ToolKind,
    ToolScope,
    ToolSelection,
    ToolUse,
)
from tests.llm.execution.support import (
    FakeClock,
    FakeProvider,
    RecordingObservations,
    _json_output,
    _models,
    _tasks,
    _tool,
)


def test_runner_reports_chain_head_capabilities_by_default() -> None:
    model = ModelSpec(
        id="vision",
        providers=(ModelProviderBinding("fake", "vision-model"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
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


async def test_runner_capability_query_returns_to_head_after_preference_expires() -> (
    None
):
    provider = FakeProvider(provider_id="fake", failures={"a": 1})
    clock = FakeClock()
    chain = ModelChain(
        profile="framework",
        model_ids=("a", "b"),
        retry_policy=RetryPolicy(
            max_retries_per_provider=1,
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
    clock.current = 6.0

    assert runner.current_model_capabilities("framework").model_id == "a"


async def test_prompt_cache_intent_does_not_require_model_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    result = await runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
            prompt_cache=PromptCache(key="framework:test"),
        )
    )

    assert _json_output(result) == {"model": "a"}


async def test_json_object_contract_does_not_require_native_json_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="a",
        providers=(ModelProviderBinding("fake", "a"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
        capabilities=frozenset({ModelCapability.TEXT_INPUT}),
    )
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    result = await runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert _json_output(result) == {"model": "a"}


async def test_runner_rejects_missing_image_capability() -> None:
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
        (await runner.run(TaskCall(profile="framework", messages=stack)))

    assert exc_info.value.reason == RUNTIME_TURN_END
    assert exc_info.value.payload["kind"] == LLMFailureKind.MODEL_CHAIN_EXHAUSTED
    assert exc_info.value.payload["last_error_type"] == "ModelCapabilityError"
    assert exc_info.value.payload["missing_capabilities"] == ["image_input"]


async def test_runner_skips_model_missing_call_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    text_model = ModelSpec(
        id="text",
        providers=(ModelProviderBinding("fake", "text"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
        capabilities=frozenset({ModelCapability.TEXT_INPUT}),
    )
    vision_model = ModelSpec(
        id="vision",
        providers=(ModelProviderBinding("fake", "vision"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
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

    result = await runner.run(TaskCall(profile="framework", messages=stack))

    assert _json_output(result) == {"model": "vision"}
    assert provider.calls == ["vision"]


async def test_runner_rejects_missing_remote_image_url_capability() -> None:
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
        (await runner.run(TaskCall(profile="framework", messages=stack)))

    assert exc_info.value.reason == RUNTIME_TURN_END


async def test_call_settings_can_add_required_capabilities() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
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
        )

    assert exc_info.value.reason == RUNTIME_TURN_END


async def test_runner_resolves_task_settings_and_call_overrides() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="a",
        providers=(ModelProviderBinding("fake", "a"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
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
                        top_p=0.9,
                        max_output_tokens=4096,
                    ),
                )
            ]
        ),
    )

    (
        await runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                settings=CallSettings(top_p=0.8, max_output_tokens=1024),
            )
        )
    )

    request = provider.requests[0]
    assert request.temperature == pytest.approx(0.6)
    assert request.top_p == pytest.approx(0.8)
    assert request.max_output_tokens == 1024
    assert request.model.adapter_options.values == {"thinking": "enabled"}


async def test_runner_applies_model_request_overrides_after_call_settings() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="a",
        providers=(ModelProviderBinding("fake", "a"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.JSON_OBJECT_OUTPUT,
            }
        ),
        request_overrides=RequestOverrides(
            temperature=1.0,
            top_p=0.7,
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
                        top_p=0.9,
                        max_output_tokens=4096,
                    ),
                )
            ]
        ),
    )

    (
        await runner.run(
            TaskCall(
                profile="framework",
                messages=MessageStack.of(UserMessage.from_text("hello")),
                settings=CallSettings(
                    temperature=0.2, top_p=0.8, max_output_tokens=1024
                ),
            )
        )
    )

    request = provider.requests[0]
    assert request.temperature == pytest.approx(1.0)
    assert request.top_p == pytest.approx(0.7)
    assert request.max_output_tokens == 128


async def test_runner_rejects_tool_task_without_tool_calling_capability() -> None:
    provider = FakeProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    with pytest.raises(RuntimeException) as exc_info:
        (
            await runner.run(
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
        )

    assert exc_info.value.reason == RUNTIME_TURN_END


async def test_runner_rejects_tool_scope_when_tool_use_is_disabled() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="tool_model",
        providers=(ModelProviderBinding("fake", "tool-model"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
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
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    tool_scope=ToolScope(tools=(_tool(),)),
                )
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END


async def test_runner_rejects_enabled_tool_use_without_visible_tools() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="tool_model",
        providers=(ModelProviderBinding("fake", "tool-model"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
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
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                )
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END


async def test_runner_rejects_forced_tool_selection_without_required_tool_use() -> None:
    provider = FakeProvider(provider_id="fake")
    model = ModelSpec(
        id="tool_model",
        providers=(ModelProviderBinding("fake", "tool-model"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
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
        (
            await runner.run(
                TaskCall(
                    profile="framework",
                    messages=MessageStack.of(UserMessage.from_text("hello")),
                    tool_scope=ToolScope(
                        tools=(_tool(),),
                        selection=ToolSelection(forced_name="read_file"),
                    ),
                )
            )
        )

    assert exc_info.value.reason == RUNTIME_TURN_END


@pytest.mark.parametrize("kind", (ToolKind.CONTROL, ToolKind.ACTION))
async def test_runner_interprets_tool_call_output(kind: ToolKind) -> None:
    tool = replace(_tool(), kind=kind)
    tool_call = ToolCallRecord(
        id="call_1",
        name="read_file",
        arguments={"path": "workspace:doc.md"},
    )

    @dataclass
    class ToolProvider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            self.requests.append(request)
            return RawResponse(
                answer_text="",
                model_id=request.model.id,
                provider_id=self.provider_id,
                tool_calls=(tool_call,),
            )

    model = ModelSpec(
        id="tool_model",
        providers=(ModelProviderBinding("fake", "tool-model"),),
        context_window_tokens=262_144,
        adapter=AdapterKind.OPENAI_CHAT,
        capabilities=frozenset(
            {
                ModelCapability.TEXT_INPUT,
                ModelCapability.TOOL_CALLING,
            }
        ),
    )
    provider = ToolProvider(provider_id="fake")
    observations = RecordingObservations()
    runner = LLMTaskRunner(
        models=ModelRegistry([model]),
        providers=ProviderRegistry([provider]),
        observations=observations,
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

    result = await runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
            tool_scope=ToolScope(tools=(tool,)),
        )
    )

    assert result.answer is None
    assert result.tool_calls == (replace(tool_call, kind=kind),)
    assert provider.requests[0].tool_scope.tools == (tool,)
    response_event = next(
        event for event in observations.events if event.name == "llm.model.response"
    )
    assert response_event.payload["tool_calls"] == [
        {
            "id": tool_call.id,
            "name": tool_call.name,
            "arguments": tool_call.arguments,
            "kind": kind.value,
        }
    ]
    assert result.raw_response is not None
    assert result.raw_response.tool_calls[0].kind is None


@pytest.mark.parametrize(
    ("answer_text", "feedback"),
    [
        ("{bad json", "Failed to parse model response as JSON object"),
        ("[]", "JSON object, got an array"),
    ],
)
async def test_runner_returns_failure_result_for_invalid_json_object(
    answer_text: str, feedback: str
) -> None:
    class BadJsonProvider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            self.requests.append(request)
            return RawResponse(
                answer_text=answer_text,
                model_id=request.model.id,
                provider_id=self.provider_id,
            )

    provider = BadJsonProvider(provider_id="fake")
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(ModelChain(profile="framework", model_ids=("a",))),
    )

    result = await runner.run(
        TaskCall(
            profile="framework",
            messages=MessageStack.of(UserMessage.from_text("hello")),
        )
    )

    assert result.status is TaskResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.reason is TaskFailureReason.INVALID_OUTPUT_PROTOCOL
    assert result.failure.scope is TaskFailureScope.OUTPUT_PROTOCOL
    assert result.failure.model_feedback is not None
    assert feedback in result.failure.model_feedback
    assert len(provider.requests) == 1


async def test_runner_reports_output_limit_before_interpreting_partial_json() -> None:
    class TruncatedProvider(FakeProvider):
        async def invoke(self, request: ProviderRequest) -> RawResponse:
            self.requests.append(request)
            return RawResponse(
                answer_text='{"text":"partial',
                model_id=request.model.id,
                provider_id=self.provider_id,
                stop_reason=ResponseStopReason.OUTPUT_LIMIT,
            )

    provider = TruncatedProvider(provider_id="fake")
    observations = RecordingObservations()
    runner = LLMTaskRunner(
        models=_models("a"),
        providers=ProviderRegistry([provider]),
        tasks=_tasks(
            ModelChain(profile="framework", model_ids=("a",)),
            max_output_tokens=2048,
        ),
        observations=observations,
    )

    result = await runner.run(
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
    request = next(
        event for event in observations.events if event.name == "llm.model.request"
    )
    assert request.payload["max_output_tokens"] == 2048
    completed = next(
        event for event in observations.events if event.name == "llm.task.completed"
    )
    assert completed.payload["reason"] == "output_limit_reached"
    assert completed.payload["scope"] == "llm.output"
    assert completed.payload["constraint"] == {"max_output_tokens": 2048}
    assert completed.payload["feedback"] == result.failure.model_feedback
