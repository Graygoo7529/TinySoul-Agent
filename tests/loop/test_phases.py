from __future__ import annotations

from collections import deque
from pathlib import Path

import pytest

from tinysoul.action import ActionEngine, ActionEngineBuilder
from tinysoul.context import (
    ContextEngineBuilder,
    WorkspaceSnapshot,
    build_workspace_sync_signal,
)
from tinysoul.context.trace import TraceKind
from tinysoul.llm.messages import MessageStack
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import RawResponse, TaskFailure, TaskResult
from tinysoul.llm.tools import ToolCallRecord, ToolKind, ToolUse
from tinysoul.loop import LoopTraceNoteKind, Phase1Unit, Phase2Unit, Phase3Unit
from tinysoul.runtime import (
    RUNTIME_TURN_END,
    RUNTIME_TURN_OUTPUT,
    CyclePhase,
    RunLevel,
    RunScope,
    RuntimeException,
    SignalBus,
)


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
    with pytest.raises(RuntimeException) as raised:
        Phase3Unit(context=context, action=action, bus=bus).run(
            normalization=phase2.normalization,
            scope=phase3_scope,
            cycle_id="cycle_1",
            turn_id=turn_id,
        )

    assert phase1.selected_domains == ("core",)
    assert phase2.normalization.calls[0].action_name == "core.answer"
    assert raised.value.reason == RUNTIME_TURN_OUTPUT
    assert raised.value.payload["text"] == "done"
    assert str(raised.value.payload["result_id"]).startswith("action_result_")
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


def test_phase1_maps_loop_scope_failure_to_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("answer now")
    action = _action_engine()
    duplicate_scope = context.control_scope()
    monkeypatch.setattr(
        ActionEngine,
        "phase1_scope",
        lambda _self: duplicate_scope,
    )

    with pytest.raises(RuntimeException) as raised:
        Phase1Unit(
            context=context,
            action=action,
            llm=FakeLLM(()),
            bus=SignalBus(),
            retry_limit=2,
        ).run(
            scope=RunScope().push(RunLevel.PHASE, CyclePhase.PHASE1.value),
            cycle_id="cycle_1",
        )

    assert raised.value.reason == RUNTIME_TURN_END
    assert raised.value.payload["kind"] == "loop.contract_violation"


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


def test_phase3_records_multiple_answers_as_loop_note() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now")
    action = _action_engine()
    bus = SignalBus()
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )
    normalization = action.normalize(
        (
            ToolCallRecord(
                id="answer_1",
                name="core.answer",
                arguments={"guide_blocks": [{"text": "answer"}]},
                kind=ToolKind.ACTION,
            ),
            ToolCallRecord(
                id="answer_2",
                name="core.answer",
                arguments={"guide_blocks": [{"text": "answer"}]},
                kind=ToolKind.ACTION,
            ),
        )
    )

    outcome = Phase3Unit(context=context, action=action, bus=bus).run(
        normalization=normalization,
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )
    summary = context.end_turn()

    assert len(outcome.results) == 2
    assert outcome.phase_results == ()
    assert context.turn_active is False
    note_message = summary.trace[-1]["message"]
    assert isinstance(note_message, dict)
    content = note_message["content"]
    assert isinstance(content, list)
    note_part = content[0]
    assert isinstance(note_part, dict)
    note = note_part["value"]
    assert isinstance(note, dict)
    assert note["kind"] == LoopTraceNoteKind.MULTIPLE_TURN_OUTPUTS.value
    result_ids = note["result_ids"]
    assert isinstance(result_ids, list)
    assert len(result_ids) == 2


def test_phase3_ignores_stale_workspace_sync_failure_from_another_call() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("reason now")
    action = _action_engine()
    bus = SignalBus()
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )
    old_scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "old_turn")
    )
    bus.emit(
        build_workspace_sync_signal(
            WorkspaceSnapshot(revision=1),
            call_id="stale_workspace_call",
            scope=old_scope,
            source="test.stale",
        )
    )
    normalization = action.normalize(
        (
            ToolCallRecord(
                id="reason_1",
                name="core.reason",
                arguments={
                    "guide_blocks": [{"text": "reason"}],
                    "output_blocks": [{"text": "return json"}],
                },
                kind=ToolKind.ACTION,
            ),
        )
    )

    outcome = Phase3Unit(context=context, action=action, bus=bus).run(
        normalization=normalization,
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert outcome.results[0].status.value == "success"


def test_phase3_rejects_failed_sync_for_current_workspace_action() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("scan now")
    bus = SignalBus()
    old_scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "old_turn")
    )

    def emit_invalid_sync(execution, execution_context):
        signal_bus = execution_context.signal_bus
        assert signal_bus is not None
        signal_bus.emit(
            build_workspace_sync_signal(
                WorkspaceSnapshot(revision=1),
                call_id=execution.call.call_id,
                scope=old_scope,
                source="test.current",
            )
        )
        return {"scanned": True}

    action = (
        ActionEngineBuilder(Path("tinysoul/action/catalog"))
        .register_native("context.trace.fold", lambda execution, context: {})
        .register_native("context.trace.inspect", lambda execution, context: {})
        .register_native("context.trace.recall", lambda execution, context: {})
        .register_native("core.answer", lambda execution, context: {"text": "done"})
        .register_native("core.reason", lambda execution, context: {"ok": True})
        .register_native("home.resource.delete", lambda execution, context: {"deleted": True})
        .register_native("home.resource.patch", lambda execution, context: {"patched": True})
        .register_native("home.resource.read", lambda execution, context: {"read": True})
        .register_native("home.resource.write", lambda execution, context: {"written": True})
        .register_native("home.top.delete", lambda execution, context: {"deleted": True})
        .register_native("home.top.patch", lambda execution, context: {"patched": True})
        .register_native("home.top.write", lambda execution, context: {"written": True})
        .register_native("home.top.search", lambda execution, context: {"items": []})
        .register_native("home.prompt_mount.patch", lambda execution, context: {"patched": True})
        .register_native("home.prompt_mount.write", lambda execution, context: {"written": True})
        .register_native("session.history.inspect", lambda execution, context: {})
        .register_native("session.history.recall", lambda execution, context: {})
        .register_native("workspace.delete", lambda execution, context: {"deleted": True})
        .register_native("workspace.describe", lambda execution, context: {"described": True})
        .register_native("workspace.patch", lambda execution, context: {"patched": True})
            .register_native("workspace.restore", lambda execution, context: {"restored": True})
            .register_native("workspace.trash.list", lambda execution, context: {"items": []})
        .register_native("workspace.scan", emit_invalid_sync)
        .register_native("workspace.write", lambda execution, context: {"written": True})
        .register_native("workspace.rewrite", lambda execution, context: {"rewritten": True})
        .build()
    )
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )
    normalization = action.normalize(
        (
            ToolCallRecord(
                id="scan_1",
                name="workspace.scan",
                arguments={},
                kind=ToolKind.ACTION,
            ),
        )
    )

    with pytest.raises(RuntimeException) as raised:
        Phase3Unit(context=context, action=action, bus=bus).run(
            normalization=normalization,
            scope=scope,
            cycle_id="cycle_1",
            turn_id=turn_id,
        )

    assert raised.value.payload["kind"] == "loop.contract_violation"


def _action_engine():
    return (
        ActionEngineBuilder(Path("tinysoul/action/catalog"))
        .register_native("context.trace.fold", lambda execution, context: {})
        .register_native("context.trace.inspect", lambda execution, context: {})
        .register_native("context.trace.recall", lambda execution, context: {})
        .register_native("core.answer", lambda execution, context: {"text": "done"})
        .register_native("core.reason", lambda execution, context: {"ok": True})
        .register_native("home.resource.delete", lambda execution, context: {"deleted": True})
        .register_native("home.resource.patch", lambda execution, context: {"patched": True})
        .register_native("home.resource.read", lambda execution, context: {"read": True})
        .register_native("home.resource.write", lambda execution, context: {"written": True})
        .register_native("home.top.delete", lambda execution, context: {"deleted": True})
        .register_native("home.top.patch", lambda execution, context: {"patched": True})
        .register_native("home.top.write", lambda execution, context: {"written": True})
        .register_native("home.top.search", lambda execution, context: {"items": []})
        .register_native("home.prompt_mount.patch", lambda execution, context: {"patched": True})
        .register_native("home.prompt_mount.write", lambda execution, context: {"written": True})
        .register_native("session.history.inspect", lambda execution, context: {})
        .register_native("session.history.recall", lambda execution, context: {})
        .register_native("workspace.delete", lambda execution, context: {"deleted": True})
        .register_native("workspace.describe", lambda execution, context: {"described": True})
        .register_native("workspace.patch", lambda execution, context: {"patched": True})
        .register_native("workspace.restore", lambda execution, context: {"restored": True})
        .register_native("workspace.trash.list", lambda execution, context: {"items": []})
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
