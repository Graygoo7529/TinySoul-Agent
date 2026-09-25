"""Action-local model input preparation and owner output contracts."""

from __future__ import annotations

from datetime import date as CalendarDate

import pytest

from tinysoul.kernel.action.tasks import ActionSkillGuidance, ActionTaskOutput
from tests.support.model_uses import action_tasks
from tinysoul.kernel.action.builtins.core import (
    CoreAnswerActionExecutor,
    CoreReasonActionExecutor,
)
from tinysoul.kernel.action.call import ActionCall, ActionExecution
from tinysoul.kernel.action.execution.preparation import ActionExecutionBuilder
from tinysoul.kernel.action.catalog.catalog import ActionCatalog
from tinysoul.kernel.action.execution.executor import ActionExecutionContext
from tinysoul.kernel.action.execution.executor import ActionExecutionControl
from tinysoul.kernel.action.result import ActionResult, ActionResultStatus
from tinysoul.kernel.action.catalog.specs import (
    ActionExecutionSpec,
    ActionDomainSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.kernel.context import ContextEngineBuilder, PromptBlock, TaskPrompt
from tinysoul.infra.json import JsonObject
from tinysoul.infra.config import ConfigError
from tinysoul.llm.protocol.messages import TextPart
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import (
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
from tinysoul.kernel.context.failures import CONTEXT_COMPRESSION_REQUIRED
from tinysoul.llm.failures import LLM_CONTEXT_CAPACITY_EXCEEDED
from tinysoul.runtime import (
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

    async def invoke(self, call: TaskCall) -> TaskResult:
        return await self.run(call)

    async def run(self, call: TaskCall) -> TaskResult:
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


class FixedRemainingControl(ActionExecutionControl):
    def __init__(self, remaining: float) -> None:
        super().__init__()
        self._remaining = remaining

    def remaining_seconds(self) -> float | None:
        return self._remaining

    def set_remaining(self, remaining: float) -> None:
        self._remaining = remaining


class ReturningAfterReserveLLMRunner(FakeLLMRunner):
    def __init__(
        self,
        control: FixedRemainingControl,
        *,
        failure: TaskFailure | None = None,
    ) -> None:
        super().__init__({"text": "done"}, failure=failure)
        self._control = control

    async def invoke(self, call: TaskCall) -> TaskResult:
        return await self.run(call)

    async def run(self, call: TaskCall) -> TaskResult:
        result = await super().run(call)
        self._control.set_remaining(4.0)
        return result


class TestReferenceResolver:
    def supports(self, link: str) -> bool:
        return link in {"test:ref", "workspace:a.md"}

    async def resolve_reference(self, link: str) -> tuple[PromptBlock, ...]:
        return (
            PromptBlock.from_text(
                "task_prompt:input:test-ref",
                f"# Reference\nresolved reference: {link}",
            ),
        )


class TestActionSkillProvider:
    async def guidance_for(
        self, *, domain: str, action_name: str
    ) -> ActionSkillGuidance:
        assert domain == "core"
        assert action_name == "core.reason"
        return ActionSkillGuidance(
            domain=("Use the core domain style.",),
            action=("Use the project rewrite style.",),
        )


async def test_llm_action_uses_splittable_prompt_blocks_and_reference_links() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    await context.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner()
    executor = CoreReasonActionExecutor(
        tasks=action_tasks(context),
        llm=llm,
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

    result = await executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload == {"ok": True}
    labels = tuple(message.label for message in llm.calls[0].messages.messages)
    assert "task_prompt:input:literal" in labels
    assert "task_prompt:input:test-ref" in labels
    text = _text_for_label(llm.calls[0], "task_prompt:input:literal")
    assert "literal input" in text


async def test_llm_action_reports_unsupported_reference_link() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    await context.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner({"text": "done"})
    executor = CoreReasonActionExecutor(tasks=action_tasks(context), llm=llm)
    execution = _execution(
        "core.reason",
        {
            "guide_blocks": [{"text": "analyze"}],
            "reference_links": ["missing:ref"],
            "output_blocks": [{"text": '{"ok": true}'}],
        },
    )

    result = await executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason == "unsupported_reference_link"
    assert llm.calls == []


async def test_llm_action_injects_domain_and_action_skills_as_guide_blocks() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    await context.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner()
    executor = CoreReasonActionExecutor(
        tasks=action_tasks(context, action_skills=TestActionSkillProvider()),
        llm=llm,
    )
    execution = _execution(
        "core.reason",
        {
            "guide_blocks": [{"text": "analyze"}],
            "output_blocks": [{"text": '{"ok": true}'}],
        },
    )

    result = await executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.SUCCESS
    labels = tuple(message.label for message in llm.calls[0].messages.messages)
    assert "task_prompt:guide:domain_skill:1" in labels
    assert "task_prompt:guide:action_skill:1" in labels
    domain_text = _text_for_label(llm.calls[0], "task_prompt:guide:domain_skill:1")
    action_text = _text_for_label(llm.calls[0], "task_prompt:guide:action_skill:1")
    assert "# Domain Skill" in domain_text
    assert "Use the core domain style." in domain_text
    assert "# Action Skill" in action_text
    assert "Use the project rewrite style." in action_text


async def test_answer_executor_uses_reference_links_and_returns_answer_payload() -> (
    None
):
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks")
    await context.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner({"text": "done"})
    executor = CoreAnswerActionExecutor(
        tasks=action_tasks(context),
        llm=llm,
        reference_resolvers=(TestReferenceResolver(),),
    )
    execution = _execution(
        "core.answer",
        {
            "guide_blocks": [{"text": "answer"}],
            "reference_links": ["workspace:a.md"],
        },
        executor_id="core.answer",
    )

    result = await executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload == {"text": "done", "references": ["workspace:a.md"]}
    labels = tuple(message.label for message in llm.calls[0].messages.messages)
    assert "task_prompt:input:test-ref" in labels


async def test_task_factory_has_no_invocation_side_effects_and_uses_binding() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("question")
    await context.open_segments(CalendarDate(2026, 7, 12))
    call = await action_tasks(context, max_output_tokens=2048).create(
        execution=_execution("core.reason", {}),
        consumer="core.reason.generate",
        prompt=TaskPrompt(guide_blocks=(PromptBlock.from_text("guide", "reason"),)),
    )
    assert call.profile == "llm_action"
    assert call.settings.max_output_tokens == 2048
    assert call.settings.answer_format is AnswerFormat.JSON_OBJECT


async def test_task_output_keeps_owner_artifact_limit_and_task_failure() -> None:
    execution = _execution("core.reason", {})
    raw = RawResponse(
        answer_text="123456",
        model_id="test",
        provider_id="test",
        stop_reason=ResponseStopReason.COMPLETE,
    )
    result = TaskResult.success(
        raw_response=raw, answer=TextAnswer("123456"), tool_calls=()
    )
    assert (
        ActionTaskOutput.text(result, execution, subject="artifact", max_chars=10)
        == "123456"
    )
    oversized = ActionTaskOutput.text(
        result, execution, subject="artifact", max_chars=4
    )
    assert isinstance(oversized, ActionResult)
    assert (
        oversized.failure is not None
        and oversized.failure.reason == "artifact_too_large"
    )
    failure = TaskResult.failure_result(
        raw_response=raw,
        failure=TaskFailure(
            reason=TaskFailureReason.OUTPUT_LIMIT_REACHED,
            scope=TaskFailureScope.OUTPUT,
            model_feedback="output limit",
            constraint={"max_output_tokens": 2048},
        ),
    )
    output = ActionTaskOutput.json(failure, execution, subject="artifact")
    assert isinstance(output, ActionResult)
    assert output.failure is not None
    assert output.failure.scope == "llm.output"
    assert output.failure.constraint == {"max_output_tokens": 2048}


async def test_auxiliary_selection_input_does_not_mark_inspect_consumed(
    monkeypatch,
) -> None:
    context = ContextEngineBuilder(system_text="identity").build()
    context.begin_turn("select relevant links")
    await context.open_segments(CalendarDate(2026, 9, 25))

    def forbidden(messages):
        raise AssertionError(
            "Only an actual decision request can mark inspect consumed"
        )

    monkeypatch.setattr(context, "mark_model_consumed", forbidden)
    selection = await action_tasks(context).selection_input(
        _execution("core.reason", {}), include_context=True
    )
    assert selection.context is not None
    await context.close_segments()


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
    executor_id: str = "core.reason",
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
                execution=ActionExecutionSpec(
                    executor=executor_id,
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
