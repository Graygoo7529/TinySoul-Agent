"""Action-local model input preparation and owner output contracts."""

from __future__ import annotations

from datetime import date as CalendarDate

import pytest

from tests.support.model_uses import action_tasks
from tinysoul.infra.json import JsonObject
from tinysoul.kernel.action.builtins.core import (
    CoreAnswerActionExecutor,
    CoreReasonActionExecutor,
)
from tinysoul.kernel.action.call import ActionCall, ActionExecution
from tinysoul.kernel.action.catalog.catalog import ActionCatalog
from tinysoul.kernel.action.catalog.specs import (
    ActionDomainSpec,
    ActionExecutionSpec,
    ActionRuntimeSpec,
    ActionSemanticSpec,
    ActionSpec,
    ActionToolSpec,
)
from tinysoul.kernel.action.execution.executor import (
    ActionExecutionContext,
    ActionExecutionControl,
)
from tinysoul.kernel.action.execution.preparation import ActionExecutionBuilder
from tinysoul.kernel.action.result import (
    ActionFailureDisposition,
    ActionResult,
    ActionResultStatus,
)
from tinysoul.kernel.action.tasks import ActionSkillGuidance, ActionTaskOutput
from tinysoul.kernel.context import ContextEngineBuilder, PromptBlock, TaskPrompt
from tinysoul.kernel.context.prompts import PromptGuidance
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


class TestActionSkillProvider:
    async def guidance_for(
        self, *, domain: str, action_name: str
    ) -> ActionSkillGuidance:
        assert domain == "core"
        assert action_name in {"core.reason", "core.answer"}
        return ActionSkillGuidance(
            domain=(
                PromptGuidance(
                    "Use the core domain style.", "home:mount/domain/core", "home"
                ),
            ),
            action=(
                PromptGuidance(
                    "Use the project rewrite style.",
                    f"home:mount/action/core/{action_name.split('.')[1]}",
                    "home",
                ),
            ),
        )


async def test_reason_uses_context_and_explicit_prompt_blocks() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks", turn_id="2026-10-06/163")
    await context.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner()
    executor = CoreReasonActionExecutor(
        tasks=action_tasks(context),
        llm=llm,
    )
    execution = _execution(
        "core.reason",
        {
            "guide_blocks": [{"label": "main", "text": "analyze"}],
            "input_blocks": [{"label": "literal", "text": "literal input"}],
            "output_blocks": [{"label": "json", "text": '{"ok": true}'}],
        },
    )

    result = await executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload == {"ok": True}
    assert llm.calls[0].settings.answer_format is AnswerFormat.JSON_OBJECT
    labels = tuple(message.label for message in llm.calls[0].messages.messages)
    assert "task_prompt:input:literal" in labels
    text = _text_for_label(llm.calls[0], "task_prompt:input:literal")
    assert "literal input" in text


@pytest.mark.parametrize("action_name", ["core.reason", "core.answer"])
async def test_llm_action_injects_domain_and_action_skills_as_guide_blocks(
    action_name: str,
) -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks", turn_id="2026-10-06/217")
    await context.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner({"text": "done"})
    executor_type = (
        CoreReasonActionExecutor
        if action_name == "core.reason"
        else CoreAnswerActionExecutor
    )
    executor = executor_type(
        tasks=action_tasks(context, action_skills=TestActionSkillProvider()),
        llm=llm,
    )
    params: JsonObject = {"guide_blocks": [{"text": "analyze"}]}
    if action_name == "core.reason":
        params["output_blocks"] = [{"text": '{"ok": true}'}]
    execution = _execution(action_name, params)

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


@pytest.mark.parametrize(
    ("body", "references"),
    [
        (
            'A "quoted" answer.\n\n- See [source](workspace:a.md#L2-L4).\n'
            '- [again](workspace:a.md#L2-L4), [memory](memory:latest#notes), '
            '[guide](home:top/agent/context/using-context), '
            '[turn](turn:trace/2026-10-01/1#action/0), '
            '[session](session:turn/2026-10-01/1).\n'
            '[web](https://example.com) [relative](a.md) [other](ftp://example.com)\n'
            '`[inline](workspace:hidden.md)`\n\n```text\n'
            '[code](workspace:code.md)\n```\n',
            [
                "workspace:a.md#L2-L4",
                "memory:latest#notes",
                "home:top/agent/context/using-context",
                "turn:trace/2026-10-01/1#action/0",
                "session:turn/2026-10-01/1",
            ],
        ),
        ('```json\n{"answer": "requested JSON"}\n```', []),
        ("long answer " + "a" * (32 * 1024), []),
    ],
    ids=["citations", "requested_json", "long_body"],
)
async def test_answer_returns_body_and_only_explicit_internal_citations(
    body: str,
    references: list[str],
) -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("user asks", turn_id="2026-10-06/250")
    await context.open_segments(CalendarDate(2026, 7, 12))
    llm = FakeLLMRunner({"text": body})
    executor = CoreAnswerActionExecutor(tasks=action_tasks(context), llm=llm)
    execution = _execution(
        "core.answer",
        {
            "guide_blocks": [{"text": "answer"}],
            "input_blocks": [{"label": "evidence", "text": "workspace:unused.md"}],
        },
        executor_id="core.answer",
    )

    result = await executor.execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.SUCCESS
    assert result.payload == {"text": body, "references": references}
    call = llm.calls[0]
    assert call.settings.answer_format is AnswerFormat.TEXT
    assert "workspace:unused.md" in _text_for_label(call, "task_prompt:input:evidence")
    assert any(
        "user asks" in part.text
        for message in call.messages.messages
        for part in message.parts
        if isinstance(part, TextPart)
    )
    await context.close_segments()


@pytest.mark.parametrize(
    "reason",
    [
        TaskFailureReason.INVALID_OUTPUT_PROTOCOL,
        TaskFailureReason.OUTPUT_LIMIT_REACHED,
        TaskFailureReason.CONTENT_FILTERED,
    ],
)
async def test_answer_executor_identifies_failed_generation(
    reason: TaskFailureReason,
) -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("question", turn_id="2026-10-22/1")
    await context.open_segments(CalendarDate(2026, 10, 22))
    feedback = "The generation did not finish successfully."
    failure = TaskFailure(
        reason=reason,
        scope=TaskFailureScope.OUTPUT_PROTOCOL,
        model_feedback=feedback,
    )
    llm = FakeLLMRunner(failure=failure)
    executor = CoreAnswerActionExecutor(tasks=action_tasks(context), llm=llm)

    result = await executor.execute(
        _execution(
            "core.answer",
            {"guide_blocks": [{"text": "answer"}]},
            executor_id="core.answer",
        ),
        ActionExecutionContext(),
    )

    assert result.status is ActionResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason == failure.reason.value
    assert result.failure.scope == failure.scope.value
    assert result.failure.disposition is (
        ActionFailureDisposition.RETRY_SAME
        if reason is TaskFailureReason.INVALID_OUTPUT_PROTOCOL
        else ActionFailureDisposition.CHANGE_REQUEST
    )
    assert "Answer generation" in result.failure.feedback
    assert feedback in result.failure.feedback
    assert len(llm.calls) == 1
    await context.close_segments()


@pytest.mark.parametrize("include_context", [True, False])
async def test_task_factory_has_no_invocation_side_effects_and_uses_binding(
    include_context: bool,
) -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("question", turn_id="2026-10-06/277")
    await context.open_segments(CalendarDate(2026, 7, 12))
    call = await action_tasks(context, max_output_tokens=2048).create(
        execution=_execution("core.reason", {}),
        consumer="core.reason.generate",
        prompt=TaskPrompt(guide_blocks=(PromptBlock.from_text("guide", "reason"),)),
        include_context=include_context,
    )
    assert call.profile == "llm-action"
    assert call.settings.max_output_tokens == 2048
    assert call.settings.answer_format is AnswerFormat.JSON_OBJECT
    assert call.prompt_cache is not None
    assert call.prompt_cache.key == "2026-10-06/277"
    assert bool(call.prompt_cache.breakpoints) is include_context


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
    assert ActionTaskOutput.text(result, execution, subject="answer") == "123456"
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


@pytest.mark.parametrize("body", ["", " \n\t"])
async def test_answer_rejects_empty_or_whitespace_body(body: str) -> None:
    context = ContextEngineBuilder(system_text="system").build()
    context.begin_turn("answer", turn_id="2026-10-06/278")
    await context.open_segments(CalendarDate(2026, 10, 6))
    executor = CoreAnswerActionExecutor(
        tasks=action_tasks(context), llm=FakeLLMRunner({"text": body})
    )
    result = await executor.execute(
        _execution("core.answer", {"guide_blocks": [{"text": "answer"}]}),
        ActionExecutionContext(),
    )
    assert result.status is ActionResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason == "missing_text_answer"
    assert result.payload == {}
    await context.close_segments()


@pytest.mark.parametrize("include_context", [True, False])
async def test_auxiliary_selection_input_does_not_mark_inspect_consumed(
    monkeypatch,
    include_context: bool,
) -> None:
    context = ContextEngineBuilder(system_text="identity").build()
    context.begin_turn("select relevant links", turn_id="2026-10-06/332")
    await context.open_segments(CalendarDate(2026, 9, 25))

    def forbidden(messages):
        raise AssertionError(
            "Only an actual decision request can mark inspect consumed"
        )

    monkeypatch.setattr(context, "mark_model_consumed", forbidden)
    selection = await action_tasks(context).selection_input(
        _execution("core.reason", {}), include_context=include_context
    )
    assert (selection.context is not None) is include_context
    assert selection.prompt_cache is not None
    assert selection.prompt_cache.key == "2026-10-06/332"
    assert bool(selection.prompt_cache.breakpoints) is include_context
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
    executor_id: str | None = None,
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
                    executor=executor_id or action_name,
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
