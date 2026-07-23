from __future__ import annotations

import pytest

from tinysoul.action.backends.llm_action import (
    ActionHow,
    LLMActionTaskRunner,
    parse_llm_action_options,
)
from tinysoul.action.builtins.core import CoreAnswerActionExecutor, CoreReasonActionExecutor
from tinysoul.action.core.call import ActionCall, ActionExecution, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.executor import ActionExecutionControl
from tinysoul.action.core.result import ActionResult, ActionResultStatus
from tinysoul.action.core.specs import (
    ActionBackendKind,
    ActionBackendSpec,
    ActionDomainSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.context import ContextEngineBuilder, PromptBlock, TaskPrompt
from tinysoul.infra.json import JsonObject
from tinysoul.infra.config import ConfigError
from tinysoul.llm.messages import TextPart
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import (
    AnswerFormat,
    JsonAnswer,
    RawResponse,
    ResponseStopReason,
    TaskFailure,
    TaskFailureReason,
    TaskFailureScope,
    TaskResult,
    TextAnswer,
)
from tinysoul.runtime import (
    CONTEXT_COMPRESSION_REQUIRED,
    RunLevel,
    RunScope,
    RuntimeException,
)


class FakeLLMRunner:
    def __init__(
        self,
        answer: JsonObject | None = None,
        runtime_error: RuntimeException | None = None,
        failure: TaskFailure | None = None,
    ) -> None:
        self.calls: list[TaskCall] = []
        self.answer = answer or {"ok": True}
        self.runtime_error = runtime_error
        self.failure = failure

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        if self.runtime_error is not None:
            raise self.runtime_error
        raw_response = RawResponse(
            answer_text="{}",
            model_id="fake",
            provider_id="fake",
            stop_reason=ResponseStopReason.COMPLETE,
        )
        if self.failure is not None:
            return TaskResult.failure_result(
                raw_response=raw_response,
                failure=self.failure,
            )
        if call.settings.answer_format is AnswerFormat.TEXT:
            text = self.answer.get("text")
            assert isinstance(text, str)
            answer = TextAnswer(text)
        else:
            answer = JsonAnswer(self.answer)
        return TaskResult.success(
            raw_response=raw_response,
            answer=answer,
            tool_calls=(),
        )


class TestReferenceResolver:
    def supports(self, link: str) -> bool:
        return link in {"test:ref", "workspace:a.md"}

    def resolve_reference(self, link: str) -> tuple[PromptBlock, ...]:
        return (
            PromptBlock.from_text(
                "task_prompt:input:test-ref",
                f"# Reference\nresolved reference: {link}",
            ),
        )


class TestActionHowProvider:
    def guidance_for(self, *, domain: str, action_name: str) -> ActionHow:
        assert domain == "core"
        assert action_name == "core.reason"
        return ActionHow(
            domain=("Use the core domain style.",),
            action=("Use the project rewrite style.",),
        )


def test_llm_action_uses_splittable_prompt_blocks_and_reference_links() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    llm = FakeLLMRunner()
    executor = CoreReasonActionExecutor(
        llm_action=LLMActionTaskRunner(llm_runner=llm, context=context),
        reference_resolvers=(TestReferenceResolver(),),
    )
    execution = _execution(
        "core.reason",
        {
            "guide_blocks": [{"label": "main", "text": "analyze"}],
            "input_blocks": [{"label": "literal", "text": "literal input"}],
            "reference_links": ["test:ref"],
            "output_blocks": [{"label": "json", "text": '{"ok": true}'}],
        },
    )

    result = executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload == {"ok": True}
    labels = tuple(message.label for message in llm.calls[0].messages.messages)
    assert "task_prompt:input:literal" in labels
    assert "task_prompt:input:test-ref" in labels
    text = _text_for_label(llm.calls[0], "task_prompt:input:literal")
    assert "literal input" in text


def test_llm_action_reports_unsupported_reference_link() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    llm = FakeLLMRunner({"text": "done"})
    executor = CoreReasonActionExecutor(
        llm_action=LLMActionTaskRunner(llm_runner=llm, context=context)
    )
    execution = _execution(
        "core.reason",
        {
            "guide_blocks": [{"text": "analyze"}],
            "reference_links": ["missing:ref"],
            "output_blocks": [{"text": '{"ok": true}'}],
        },
    )

    result = executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason == "unsupported_reference_link"
    assert llm.calls == []


def test_llm_action_cancellation_stops_before_nested_task() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    llm = FakeLLMRunner()
    control = ActionExecutionControl()
    control.request_cancel("timeout")
    executor = CoreAnswerActionExecutor(
        llm_action=LLMActionTaskRunner(llm_runner=llm, context=context)
    )

    result = executor.execute(
        _execution(
            "core.answer",
            {"guide_blocks": [{"text": "answer"}]},
            handler="core.answer",
        ),
        ActionExecutionContext(control=control),
    )

    assert result.status is ActionResultStatus.TIMEOUT
    assert result.failure is not None
    assert result.failure.reason == "cancelled"
    assert llm.calls == []


def test_llm_action_injects_domain_and_action_how_as_guide_blocks() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    llm = FakeLLMRunner()
    executor = CoreReasonActionExecutor(
        llm_action=LLMActionTaskRunner(
            llm_runner=llm,
            context=context,
            action_how=TestActionHowProvider(),
        ),
    )
    execution = _execution(
        "core.reason",
        {
            "guide_blocks": [{"text": "analyze"}],
            "output_blocks": [{"text": '{"ok": true}'}],
        },
    )

    result = executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.SUCCESS
    labels = tuple(message.label for message in llm.calls[0].messages.messages)
    assert "task_prompt:guide:domain_how:1" in labels
    assert "task_prompt:guide:action_how:1" in labels
    domain_text = _text_for_label(llm.calls[0], "task_prompt:guide:domain_how:1")
    action_text = _text_for_label(llm.calls[0], "task_prompt:guide:action_how:1")
    assert "# Domain HOW" in domain_text
    assert "Use the core domain style." in domain_text
    assert "# Action HOW" in action_text
    assert "Use the project rewrite style." in action_text


def test_answer_executor_uses_reference_links_and_returns_answer_payload() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    llm = FakeLLMRunner({"text": "done"})
    executor = CoreAnswerActionExecutor(
        llm_action=LLMActionTaskRunner(llm_runner=llm, context=context),
        reference_resolvers=(TestReferenceResolver(),),
    )
    execution = _execution(
        "core.answer",
        {
            "guide_blocks": [{"text": "answer"}],
            "reference_links": ["workspace:a.md"],
        },
        handler="core.answer",
    )

    result = executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload == {"text": "done", "references": ["workspace:a.md"]}
    labels = tuple(message.label for message in llm.calls[0].messages.messages)
    assert "task_prompt:input:test-ref" in labels


def test_llm_action_context_pressure_carries_active_resource_links() -> None:
    context = ContextEngineBuilder(system_text="system").build()
    pressure = RuntimeException(
        reason=CONTEXT_COMPRESSION_REQUIRED,
        message="model context pressure",
        payload={"model_id": "small"},
    )
    context.begin_turn("user asks")
    runner = LLMActionTaskRunner(
        llm_runner=FakeLLMRunner(runtime_error=pressure),
        context=context,
    )
    execution = _execution(
        "core.reason",
        {
            "target_link": "workspace:target.md",
            "reference_links": ["workspace:reference.md", "home:why/example"],
        },
    )

    with pytest.raises(RuntimeException) as exc_info:
        runner.run_json(
            execution=execution,
            prompt=TaskPrompt(
                guide_blocks=(PromptBlock.from_text("guide", "reason"),),
            ),
            subject="test",
        )

    assert exc_info.value.reason == CONTEXT_COMPRESSION_REQUIRED
    assert exc_info.value.payload["protected_resource_links"] == [
        "workspace:target.md",
        "workspace:reference.md",
        "home:why/example",
    ]


def test_llm_action_text_artifact_uses_action_limits() -> None:
    context = ContextEngineBuilder(system_text="system").build()
    context.begin_turn("write a document")
    llm = FakeLLMRunner({"text": "complete artifact"})
    runner = LLMActionTaskRunner(llm_runner=llm, context=context)
    execution = _execution(
        "core.reason",
        {},
        options={"max_output_tokens": 16384, "max_output_chars": 100},
    )

    result = runner.run_text(
        execution=execution,
        prompt=TaskPrompt(
            guide_blocks=(PromptBlock.from_text("guide", "write"),),
        ),
        subject="Artifact task",
    )

    assert result == "complete artifact"
    assert llm.calls[0].settings.answer_format is AnswerFormat.TEXT
    assert llm.calls[0].settings.max_output_tokens == 16384


def test_llm_action_text_artifact_limit_returns_bounded_failure() -> None:
    context = ContextEngineBuilder(system_text="system").build()
    context.begin_turn("write a document")
    runner = LLMActionTaskRunner(
        llm_runner=FakeLLMRunner({"text": "too long"}),
        context=context,
    )
    execution = _execution(
        "core.reason",
        {},
        options={"max_output_chars": 4},
    )

    result = runner.run_text(
        execution=execution,
        prompt=TaskPrompt(
            guide_blocks=(PromptBlock.from_text("guide", "write"),),
        ),
        subject="Artifact task",
    )

    assert isinstance(result, ActionResult)
    assert result.payload == {}
    assert result.failure is not None
    assert result.failure.to_json() == {
        "reason": "artifact_too_large",
        "scope": "action.artifact",
        "disposition": "change_request",
        "feedback": "Artifact task exceeded its artifact character limit of 4.",
        "constraint": {"max_output_chars": 4},
    }
    assert result.frame_data["observed_chars"] == 8


def test_llm_action_output_limit_preserves_recovery_scope() -> None:
    context = ContextEngineBuilder(system_text="system").build()
    context.begin_turn("write a document")
    failure = TaskFailure(
        model_feedback="Model generation reached its output token limit.",
        reason=TaskFailureReason.OUTPUT_LIMIT_REACHED,
        scope=TaskFailureScope.OUTPUT,
        constraint={"max_output_tokens": 2048},
    )
    runner = LLMActionTaskRunner(
        llm_runner=FakeLLMRunner(failure=failure),
        context=context,
    )

    result = runner.run_text(
        execution=_execution("core.reason", {}),
        prompt=TaskPrompt(
            guide_blocks=(PromptBlock.from_text("guide", "write"),),
        ),
        subject="Artifact task",
    )

    assert isinstance(result, ActionResult)
    assert result.failure is not None
    assert result.failure.to_json() == {
        "reason": "output_limit_reached",
        "scope": "llm.output",
        "disposition": "change_request",
        "feedback": "Model generation reached its output token limit.",
        "constraint": {"max_output_tokens": 2048},
    }


def test_llm_action_backend_options_reject_unknown_or_invalid_limits() -> None:
    assert parse_llm_action_options(
        {"max_output_tokens": 8, "max_output_chars": 16},
        key="action.backend.options",
    ).max_output_chars == 16
    with pytest.raises(ConfigError, match="Unsupported llm_action backend option"):
        parse_llm_action_options({"legacy": 1}, key="action.backend.options")
    with pytest.raises(ConfigError, match="positive integer"):
        parse_llm_action_options(
            {"max_output_tokens": 0},
            key="action.backend.options",
        )


def _text_for_label(call: TaskCall, label: str) -> str:
    for message in call.messages.messages:
        if message.label != label:
            continue
        parts = [part.text for part in message.parts if isinstance(part, TextPart)]
        return "\n".join(parts)
    raise AssertionError(f"Missing message label: {label}")


def _execution(
    action_name: str,
    params: JsonObject,
    *,
    handler: str = "core.reason",
    options: JsonObject | None = None,
) -> ActionExecution:
    catalog = ActionCatalog(
        domains=(ActionDomainSpec(name="core", description="Core."),),
        actions=(
            ActionSpec(
                name=action_name,
                domain="core",
                tool=ActionToolSpec(
                    name=action_name,
                    description="Reason.",
                    schema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                ),
                semantic=ActionSemanticSpec(),
                runtime=ActionRuntimeSpec(),
                backend=ActionBackendSpec(
                    kind=ActionBackendKind.LLM_ACTION,
                    handler=handler,
                    options=options or {},
                ),
            ),
        ),
    )
    preparation = ActionExecutionBuilder().prepare_batch(
        (ActionCall("call_1", action_name, params, 1),),
        catalog=catalog,
        scope=RunScope().push(RunLevel.PHASE, "phase3"),
        batch_id="batch_1",
    )
    return preparation.batch.executions[0]
