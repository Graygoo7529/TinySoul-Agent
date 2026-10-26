from __future__ import annotations
from datetime import date as CalendarDate
from tinysoul.kernel.context import ContextEngineBuilder
from tinysoul.kernel.context.builtin.trace import TraceKind
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind, ToolUse
from tinysoul.kernel.loop import Phase1Unit, Phase2Unit, Phase3Unit
from tinysoul.kernel.loop.lifecycle.completion import AnswerCompletionDetector
from tinysoul.runtime import CyclePhase, RunLevel, RunScope, SignalBus
from tests.kernel.loop.phases.support import (
    FakeLLM,
    RecordingObservations,
    _action_engine,
    _tool_result,
)


async def test_phase_units_select_normalize_execute_and_trace_answer() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now", turn_id="2026-10-06/171")
    await context.open_segments(CalendarDate(2026, 7, 12))
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
    observations = RecordingObservations()
    base_scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
    )
    phase1_scope = base_scope.push(RunLevel.PHASE, CyclePhase.PHASE1.value)
    phase2_scope = base_scope.push(RunLevel.PHASE, CyclePhase.PHASE2.value)
    phase3_scope = base_scope.push(RunLevel.PHASE, CyclePhase.PHASE3.value)

    phase1 = await Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        task_profile="framework",
    ).run(scope=phase1_scope, cycle_id="cycle_1")
    phase2 = await Phase2Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        task_profile="framework",
        observations=observations,
    ).run(
        selected_domains=phase1.selected_domains,
        scope=phase2_scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )
    phase3 = await Phase3Unit(
        context=context,
        action=action,
        bus=bus,
        observations=observations,
        completion_detector=AnswerCompletionDetector(),
    ).run(
        normalization=phase2.normalization,
        scope=phase3_scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert phase1.selected_domains == ("core",)
    assert phase2.normalization.calls[0].action_name == "core.answer"
    assert phase3.completion is not None
    assert phase3.completion["kind"] == "answer"
    assert phase3.completion["text"] == "done"
    assert str(phase3.completion["result_id"]).startswith("action_result_")
    assert context.trace_kinds() == (
        TraceKind.INPUT,
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
    )
    assert all(call.settings.tool_use is ToolUse.REQUIRED for call in llm.calls)
    action_events = [
        event for event in observations.events if event.name.startswith("action.")
    ]
    assert [event.name for event in action_events] == [
        "action.call",
        "action.result",
    ]
    assert [call.profile for call in llm.calls] == ["framework", "framework"]
    assert action_events[0].payload["call_id"] == "answer_1"
    assert action_events[1].payload["call_id"] == "answer_1"
