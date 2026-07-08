from __future__ import annotations

from collections import deque
from pathlib import Path

from tinysoul.action import ActionEngineBuilder, ActionResultStatus
from tinysoul.context import ContextEngineBuilder, TraceKind
from tinysoul.llm.messages import MessageStack
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import RawResponse, TaskFailure, TaskResult
from tinysoul.llm.tools import ToolCallRecord, ToolKind, ToolUse
from tinysoul.loop import Phase1Unit, Phase2Unit, Phase3Unit
from tinysoul.runtime import CyclePhase, RunLevel, RunScope, SignalBus


class FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self.results.popleft()


def test_phase_units_select_normalize_execute_and_trace_answer() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now")
    action = _action_engine()
    bus = SignalBus()
    llm = FakeLLM(
        (
            _tool_result(
                ToolCallRecord(
                    id="select_1",
                    name="select_action_domains",
                    arguments={"domains": ["core"]},
                    kind=ToolKind.CONTROL,
                )
            ),
            _tool_result(
                ToolCallRecord(
                    id="answer_1",
                    name="core.answer",
                    arguments={"guide_blocks": [{"text": "answer"}]},
                    kind=ToolKind.ACTION,
                )
            ),
        )
    )
    base_scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
    )
    phase1_scope = base_scope.push(RunLevel.PHASE, CyclePhase.PHASE1.value)
    phase2_scope = base_scope.push(RunLevel.PHASE, CyclePhase.PHASE2.value)
    phase3_scope = base_scope.push(RunLevel.PHASE, CyclePhase.PHASE3.value)

    phase1 = Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=2,
    ).run(scope=phase1_scope, cycle_id="cycle_1")
    phase2 = Phase2Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=2,
    ).run(
        selected_domains=phase1.selected_domains,
        scope=phase2_scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )
    phase3 = Phase3Unit(context=context, action=action, bus=bus).run(
        normalization=phase2.normalization,
        scope=phase3_scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert phase1.selected_domains == ("core",)
    assert phase2.normalization.calls[0].action_name == "core.answer"
    assert phase3.answered is True
    assert phase3.results[0].status is ActionResultStatus.SUCCESS
    assert context.trace_kinds() == (
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
    )
    assert all(call.settings.tool_use is ToolUse.REQUIRED for call in llm.calls)


def test_phase1_retries_invalid_domain_selection() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("answer now")
    action = _action_engine()
    bus = SignalBus()
    llm = FakeLLM(
        (
            _tool_result(
                ToolCallRecord(
                    id="select_bad",
                    name="select_action_domains",
                    arguments={"domains": ["missing"]},
                    kind=ToolKind.CONTROL,
                )
            ),
            _tool_result(
                ToolCallRecord(
                    id="select_ok",
                    name="select_action_domains",
                    arguments={"domains": ["core"]},
                    kind=ToolKind.CONTROL,
                )
            ),
        )
    )
    scope = RunScope().push(RunLevel.PHASE, CyclePhase.PHASE1.value)

    outcome = Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=2,
    ).run(scope=scope, cycle_id="cycle_1")

    assert outcome.selected_domains == ("core",)
    assert outcome.attempts == 2


def test_phase2_records_note_when_task_failures_exhaust_retries() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now")
    action = _action_engine()
    bus = SignalBus()
    llm = FakeLLM(
        (
            _task_failure("missing tool call"),
            _task_failure("still missing tool call"),
        )
    )
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE2.value)
    )

    outcome = Phase2Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=2,
    ).run(
        selected_domains=("core",),
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert outcome.normalization.calls == ()
    assert outcome.attempts == 2
    assert context.trace_kinds() == (
        TraceKind.PHASE_NOTE,
    )


def _action_engine():
    return (
        ActionEngineBuilder(Path("tinysoul/action/builtin"))
        .register_native("llm_action.answer", lambda execution, context: {"text": "done"})
        .register_native("llm_action.reason", lambda execution, context: {"ok": True})
        .register_native("home.resource.read", lambda execution, context: {"read": True})
        .register_native("workspace.delete", lambda execution, context: {"deleted": True})
        .register_native("workspace.describe", lambda execution, context: {"described": True})
        .register_native("workspace.patch", lambda execution, context: {"patched": True})
        .register_native("workspace.scan", lambda execution, context: {"scanned": True})
        .register_native("workspace.write", lambda execution, context: {"written": True})
        .register_native("workspace.rewrite", lambda execution, context: {"rewritten": True})
        .build()
    )


def _tool_result(*tool_calls: ToolCallRecord) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="",
            model_id="fake",
            provider_id="fake",
            tool_calls=tool_calls,
        ),
        answer=None,
        tool_calls=tool_calls,
    )


def _task_failure(feedback: str) -> TaskResult:
    return TaskResult.failure_result(
        raw_response=RawResponse(
            answer_text="",
            model_id="fake",
            provider_id="fake",
        ),
        failure=TaskFailure(model_feedback=feedback),
    )


def _stack() -> MessageStack:
    return MessageStack()
