from __future__ import annotations

from tinysoul.action.backends.llm_step import LLMStepActionExecutor
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
from tinysoul.context import ContextEngineBuilder, PromptBlock
from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import TextPart
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.runtime import RunLevel, RunScope


class FakeLLMRunner:
    def __init__(self) -> None:
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return TaskResult.success(
            raw_response=RawResponse(
                answer_text='{"ok":true}',
                model_id="fake",
                provider_id="fake",
            ),
            answer=JsonAnswer({"ok": True}),
            tool_calls=(),
        )


class TestReferenceResolver:
    def supports(self, kind: str) -> bool:
        return kind == "test.ref"

    def resolve(self, reference: JsonObject) -> tuple[PromptBlock, ...]:
        return (
            PromptBlock.from_text(
                "task_prompt:input:test-ref",
                "# Reference\nresolved reference",
            ),
        )


def test_llm_step_uses_splittable_task_inputs_and_references() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    llm = FakeLLMRunner()
    executor = LLMStepActionExecutor(
        llm_runner=llm,
        context=context,
        reference_resolvers=(TestReferenceResolver(),),
    )
    execution = _execution(
        "core.reason",
        {
            "guide": "analyze",
            "task_inputs": [{"label": "literal", "text": "literal input"}],
            "references": [{"type": "test.ref"}],
            "output_desc": '{"ok": true}',
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


def test_llm_step_reports_unsupported_reference_type() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    llm = FakeLLMRunner()
    executor = LLMStepActionExecutor(llm_runner=llm, context=context)
    execution = _execution(
        "core.reason",
        {"guide": "analyze", "references": [{"type": "missing.ref"}]},
    )

    result = executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.FAILED
    assert result.frame_data["reason"] == "unsupported_reference_type"
    assert llm.calls == []


def _text_for_label(call: TaskCall, label: str) -> str:
    for message in call.messages.messages:
        if message.label != label:
            continue
        parts = [part.text for part in message.parts if isinstance(part, TextPart)]
        return "\n".join(parts)
    raise AssertionError(f"Missing message label: {label}")


def _execution(action_name: str, params: JsonObject) -> ActionExecution:
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
                    kind=ActionBackendKind.LLM_STEP,
                    handler="llm_step.context_task",
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
