from __future__ import annotations

import pytest

from tinysoul.action.backends.llm_action import ActionHow, LLMActionTaskRunner
from tinysoul.action.builtins.core import CoreAnswerActionExecutor, CoreReasonActionExecutor
from tinysoul.action.core.call import ActionCall, ActionExecution, ActionExecutionBuilder
from tinysoul.action.core.catalog import ActionCatalog
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.action.core.result import ActionResultStatus
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
from tinysoul.llm.messages import TextPart
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import JsonAnswer, RawResponse, TaskResult
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
    ) -> None:
        self.calls: list[TaskCall] = []
        self.answer = answer or {"ok": True}
        self.runtime_error = runtime_error

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        if self.runtime_error is not None:
            raise self.runtime_error
        return TaskResult.success(
            raw_response=RawResponse(
                answer_text="{}",
                model_id="fake",
                provider_id="fake",
            ),
            answer=JsonAnswer(self.answer),
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
    assert result.frame_data["reason"] == "unsupported_reference_link"
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
