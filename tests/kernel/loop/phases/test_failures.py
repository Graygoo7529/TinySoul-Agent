from __future__ import annotations
from tests.support.actions import sample_catalog
from datetime import date as CalendarDate
from tinysoul.plugins.workspace.projection import workspace_refresh_signal
from typing import cast
import pytest
from tinysoul.kernel.action import (
    ActionEngine,
    ActionNormalization,
    ActionPhaseResult,
    ActionPhaseResultStage,
    ActionLocalFailure,
    ActionFailureDisposition,
    ActionScopePreparation,
)
from tinysoul.kernel.context import (
    ContextEngineBuilder,
    ControlResult,
    ControlResultStage,
)
from tinysoul.kernel.context.builtin.trace import TraceKind
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.kernel.loop import (
    CycleRunner,
    Phase1Outcome,
    Phase1Unit,
    Phase2Outcome,
    Phase2Unit,
    Phase3Outcome,
    Phase3Unit,
    PhaseFailure,
)
from tinysoul.kernel.loop.lifecycle.completion import AnswerCompletionDetector
from tinysoul.runtime import (
    RUNTIME_TURN_END,
    CyclePhase,
    RunLevel,
    RunScope,
    RuntimeException,
    SignalBus,
    RuntimeTrap,
    TrapHandlerRegistry,
)
from tests.support.actions import FunctionActionEngineBuilder
from tests.kernel.loop.phases.support import (
    FakeLLM,
    RecordingObservations,
    _action_engine,
    _task_failure,
    _tool_result,
)


async def test_phase1_returns_invalid_domain_selection_for_next_cycle() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now", turn_id="2026-10-06/666")
    await context.open_segments(CalendarDate(2026, 7, 12))
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
    scope = (
        RunScope()
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.PHASE, CyclePhase.PHASE1.value)
    )

    outcome = await Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        task_profile="framework",
    ).run(scope=scope, cycle_id="cycle_1")

    assert outcome.selected_domains == ()
    assert outcome.attempts == 1
    assert outcome.failure is not None
    assert outcome.failure.reason == "invalid_domain_selection"
    assert len(llm.calls) == 1


async def test_phase1_returns_provider_failure_for_next_cycle() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now", turn_id="2026-10-06/713")
    await context.open_segments(CalendarDate(2026, 7, 12))
    action = _action_engine()
    llm = FakeLLM(
        (
            _task_failure("Expected forced tool call: select_action_domains"),
            _tool_result(
                ToolCallRecord(
                    id="select_core",
                    name="select_action_domains",
                    arguments={"domains": ["core"]},
                    kind=ToolKind.CONTROL,
                )
            ),
        )
    )

    outcome = await Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=SignalBus(),
        task_profile="framework",
    ).run(
        scope=RunScope()
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.PHASE, CyclePhase.PHASE1.value),
        cycle_id="cycle_1",
    )

    assert outcome.selected_domains == ()
    assert outcome.failure is not None
    assert outcome.failure.reason == "framework_task_failure"
    assert len(llm.calls) == 1


async def test_phase1_invalid_selection_returns_local_failure() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now", turn_id="2026-10-06/751")
    await context.open_segments(CalendarDate(2026, 7, 12))
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
                ),
                ToolCallRecord(
                    id="set_todo",
                    name="set_todo",
                    arguments={
                        "key": "should_not_apply",
                        "content": "Invalid domain response",
                        "status": "in_progress",
                    },
                    kind=ToolKind.CONTROL,
                ),
            ),
            _tool_result(
                ToolCallRecord(
                    id="select_bad_2",
                    name="select_action_domains",
                    arguments={"domains": ["also_missing"]},
                    kind=ToolKind.CONTROL,
                )
            ),
        )
    )
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE1.value)
    )

    outcome = await Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        task_profile="framework",
    ).run(scope=scope, cycle_id="cycle_1")

    assert outcome.selected_domains == ()
    assert outcome.failure is not None
    assert outcome.failure.reason == "invalid_domain_selection"
    assert outcome.attempts == 1
    assert outcome.failure.feedback
    assert len(llm.calls) == 1
    assert context.trace_kinds() == (TraceKind.INPUT, TraceKind.PHASE_NOTE)
    assert context.working_snapshot()["todos"] == []


async def test_phase1_maps_loop_scope_failure_to_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("answer now", turn_id="2026-10-06/879")
    await context.open_segments(CalendarDate(2026, 7, 12))
    action = _action_engine()
    duplicate_scope = context.control_scope()
    monkeypatch.setattr(
        ActionEngine,
        "phase1_scope",
        lambda _self: duplicate_scope,
    )

    with pytest.raises(RuntimeException) as raised:
        (
            await Phase1Unit(
                context=context,
                action=action,
                llm=FakeLLM(()),
                bus=SignalBus(),
                task_profile="framework",
            ).run(
                scope=RunScope().push(RunLevel.PHASE, CyclePhase.PHASE1.value),
                cycle_id="cycle_1",
            )
        )

    assert raised.value.reason == RUNTIME_TURN_END
    assert raised.value.payload["kind"] == "loop.contract_violation"


async def test_phase2_returns_framework_failure_for_next_cycle() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now", turn_id="2026-10-06/909")
    await context.open_segments(CalendarDate(2026, 7, 12))
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
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE2.value)
    )

    outcome = await Phase2Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        task_profile="framework",
    ).run(
        selected_domains=("core",),
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert outcome.normalization.calls == ()
    assert outcome.attempts == 1
    assert outcome.failure is not None
    assert outcome.failure.reason == "framework_task_failure"
    assert len(llm.calls) == 1
    assert context.trace_kinds() == (TraceKind.INPUT, TraceKind.PHASE_NOTE)


async def test_phase2_scope_failure_stops_before_task_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("run the selected action", turn_id="2026-10-06/930")
    await context.open_segments(CalendarDate(2026, 7, 12))
    action = _action_engine()
    phase_result = ActionPhaseResult.failed(
        phase=CyclePhase.PHASE2,
        stage=ActionPhaseResultStage.SCOPE,
        failure=ActionLocalFailure(
            reason="scope_preparation_failed",
            scope="action.scope",
            disposition=ActionFailureDisposition.STOP,
            feedback="No actions are available for the selected domain.",
        ),
    )
    monkeypatch.setattr(
        ActionEngine,
        "phase2_scope",
        lambda *args, **kwargs: ActionScopePreparation(
            tool_scope=None,
            phase_results=(phase_result,),
        ),
    )
    llm = FakeLLM(())
    scope = (
        RunScope()
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.PHASE, CyclePhase.PHASE2.value)
    )

    outcome = await Phase2Unit(
        context=context,
        action=action,
        llm=llm,
        bus=SignalBus(),
        task_profile="framework",
    ).run(
        selected_domains=("core",),
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert outcome.failure is not None
    assert outcome.failure.reason == "action_scope_preparation_failed"
    assert outcome.failure.phase is CyclePhase.PHASE2
    assert llm.calls == []


async def test_cycle_stops_after_phase2_failure_without_running_phase3() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("write a report", turn_id="2026-10-06/950")
    await context.open_segments(CalendarDate(2026, 7, 12))
    action = _action_engine()
    bus = SignalBus()

    class _Phase1:
        async def run(self, **_kwargs: object) -> Phase1Outcome:
            return Phase1Outcome(
                selected_domains=("core",),
                control_results=(
                    ControlResult.failed(
                        call_id="missing",
                        tool_name="remove_todo",
                        sequence=1,
                        model_feedback="Unknown todo key",
                        stage=ControlResultStage.CONSUME,
                    ),
                ),
            )

    class _Phase2:
        async def run(self, **_kwargs: object) -> Phase2Outcome:
            return Phase2Outcome(
                normalization=ActionNormalization(),
                failure=PhaseFailure(
                    phase=CyclePhase.PHASE2,
                    reason="framework_task_failure",
                    feedback=("Phase2 did not produce an action call.",),
                ),
            )

    class _Phase3:
        calls = 0

        async def run(self, **_kwargs: object) -> Phase3Outcome:
            self.calls += 1
            return Phase3Outcome()

    phase3 = _Phase3()
    observations = RecordingObservations()
    runner = CycleRunner(
        context=context,
        bus=bus,
        trap=RuntimeTrap(registry=TrapHandlerRegistry()),
        phase1=cast(Phase1Unit, _Phase1()),
        phase2=cast(Phase2Unit, _Phase2()),
        phase3=cast(Phase3Unit, phase3),
        observations=observations,
    )
    scope = RunScope().push(RunLevel.AGENT, "program").push(RunLevel.TURN, turn_id)

    outcome = await runner.run(
        turn_id=turn_id,
        cycle_index=1,
        scope=scope,
    )

    assert outcome.phase_failure is not None
    assert outcome.phase_failure.phase is CyclePhase.PHASE2
    assert phase3.calls == 0
    completed = next(
        event
        for event in observations.events
        if event.name == "loop.phase.completed" and event.payload["phase"] == "phase1"
    )
    assert completed.payload["selected_domains"] == ["core"]
    assert completed.payload["control_results"] == [
        {
            "call_id": "missing",
            "tool_name": "remove_todo",
            "status": "failed",
            "stage": "consume",
            "feedback": "Unknown todo key",
        }
    ]


async def test_phase3_returns_conflicting_answer_intents_as_local_failure() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now", turn_id="2026-10-06/1013")
    await context.open_segments(CalendarDate(2026, 7, 12))
    action = _action_engine()
    bus = SignalBus()
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
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

    outcome = await Phase3Unit(
        context=context,
        action=action,
        bus=bus,
        completion_detector=AnswerCompletionDetector(),
    ).run(normalization=normalization, scope=scope, cycle_id="cycle_1", turn_id=turn_id)
    assert outcome.failure is not None
    assert outcome.failure.reason == "conflicting_turn_intents"
    assert outcome.completion is None
    assert context.turn_active is True


async def test_phase3_rejects_misdirected_internal_update_even_from_another_call() -> (
    None
):
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("reason now", turn_id="2026-10-06/1057")
    await context.open_segments(CalendarDate(2026, 7, 12))
    action = _action_engine()
    bus = SignalBus()
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )
    old_scope = (
        RunScope().push(RunLevel.AGENT, "program").push(RunLevel.TURN, "old_turn")
    )
    bus.emit(
        workspace_refresh_signal(
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

    with pytest.raises(RuntimeException) as raised:
        await Phase3Unit(context=context, action=action, bus=bus).run(
            normalization=normalization,
            scope=scope,
            cycle_id="cycle_1",
            turn_id=turn_id,
        )
    assert raised.value.payload["kind"] == "loop.internal_failure"


async def test_phase3_rejects_failed_sync_for_current_workspace_action() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("scan now", turn_id="2026-10-06/1104")
    await context.open_segments(CalendarDate(2026, 7, 12))
    bus = SignalBus()
    old_scope = (
        RunScope().push(RunLevel.AGENT, "program").push(RunLevel.TURN, "old_turn")
    )

    def emit_invalid_sync(execution, execution_context):
        signal_bus = execution_context.signal_bus
        assert signal_bus is not None
        signal_bus.emit(
            workspace_refresh_signal(
                call_id=execution.call.call_id,
                scope=old_scope,
                source="test.current",
            )
        )
        return {"scanned": True}

    action = (
        FunctionActionEngineBuilder(sample_catalog())
        .register_function("workspace.list", emit_invalid_sync)
        .build()
    )
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )
    normalization = action.normalize(
        (
            ToolCallRecord(
                id="scan_1",
                name="workspace.list",
                arguments={},
                kind=ToolKind.ACTION,
            ),
        )
    )

    with pytest.raises(RuntimeException) as raised:
        (
            await Phase3Unit(context=context, action=action, bus=bus).run(
                normalization=normalization,
                scope=scope,
                cycle_id="cycle_1",
                turn_id=turn_id,
            )
        )

    assert raised.value.payload["kind"] == "loop.internal_failure"
