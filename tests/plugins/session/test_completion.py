from __future__ import annotations

from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus

from dataclasses import replace

import pytest

from tinysoul.kernel.action import ActionResultStatus
from tinysoul.kernel.action.call import ExecutionState
from tinysoul.kernel.context.builtin.trace import SealedTurnTrace
from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.session.completion import project_turn_record
from tinysoul.plugins.session.records.models import (
    SessionActionOutcome,
    SessionOutputRecord,
)

from .synthetic import SyntheticAction, completion

DAY = CalendarDay.parse("2026-07-25")


async def test_ordered_facts_survive_parallel_completion_and_session_reopen(tmp_path) -> None:
    from tinysoul.kernel.action.call import ActionCall, ActionFramework, ExecutionFact
    from tinysoul.kernel.action.result import ActionResult
    from tinysoul.kernel.context import ContextEngineBuilder, build_input_append_signal, build_trace_phase_note_signal
    from tinysoul.kernel.context.builtin.trace import TraceFactKind
    from tinysoul.plugins.session import SessionEngine, SessionSettings
    from tinysoul.plugins.session.records.store import SessionStore
    from tinysoul.runtime import RunLevel, RunScope, SignalBus

    context = ContextEngineBuilder(system_text="test").build()
    turn_id = context.begin_turn("start", turn_id="ordered")
    await context.open_segments(DAY.value)
    scope = RunScope().push(RunLevel.TURN, turn_id)
    calls = tuple(ActionCall(f"call_{i}", "test.run", {"task": i}, sequence=i + 1)
                  for i in range(5))
    context.register_action_calls(calls, cycle_id="cycle_1")
    frames = tuple(ActionFramework(invoke_id=f"invoke_{i}", batch_id="batch", scope=scope,
                                   domain="test", turn_id=turn_id, cycle_id="cycle_1")
                   for i in range(5))
    for call, frame in zip(calls[:4], frames[:4]):
        context.record_execution(ExecutionFact(call, frame, ExecutionState.STARTED))

    def settle(index: int) -> None:
        call, frame = calls[index], frames[index]
        result = ActionResult.success(call_id=call.call_id, action_name=call.action_name,
                                      invoke_id=frame.invoke_id, batch_id="batch", domain="test",
                                      sequence=call.sequence, payload={"done": index})
        context.record_execution(ExecutionFact(call, frame, ExecutionState.SETTLED, result))

    settle(1)
    bus = SignalBus()
    bus.emit(build_input_append_signal("changed request", input_id="append", admission_sequence=4,
                                      received_at=42, scope=scope, source="test"))
    bus.emit(build_trace_phase_note_signal(
        {"kind": "environment_event", "payload": {"job_id": "job-1", "state": "completed"}},
        scope=scope, source="test"))
    await context.consume_signals(bus)
    context.merge_pending_inputs()
    settle(0)
    for index, state in ((2, ExecutionState.CANCELLED), (3, ExecutionState.UNKNOWN)):
        context.record_execution(ExecutionFact(calls[index], frames[index], state))
    context.compress(required_chars=100000)
    source = context.end_turn()
    await context.close_segments()

    session = SessionEngine(SessionSettings(root=tmp_path / "session"))
    session.initialize_day(DAY)
    session.record_turn(
        source, day=DAY, output=SessionOutputRecord(text="final-answer-marker"),
        exhausted=False, status=TurnOutcomeStatus.ANSWERED,
    )
    stored = SessionStore(root=session.root).load_record("session:turn/ordered")
    settled = [item.ref for item in stored.timeline if item.kind is TraceFactKind.ACTION_SETTLED]
    assert settled == ["session:turn/ordered#action/1", "session:turn/ordered#action/0"]
    visible = next(index for index, item in enumerate(stored.timeline)
                   if item.kind is TraceFactKind.INPUT_VISIBLE and item.ref.endswith("#input/1"))
    settlements = [index for index, item in enumerate(stored.timeline)
                   if item.kind is TraceFactKind.ACTION_SETTLED]
    assert settlements[0] < visible < settlements[1]
    admitted = next(item for item in stored.timeline if item.admission_sequence == 4)
    assert admitted.ref.endswith("#input/1")
    assert stored.inputs[1].received_at == 42
    assert [item.outcome.value for item in stored.actions[2:]] == ["cancelled", "unknown", "not_executed"]
    assert all(not item.result for item in stored.actions[2:])
    assert len(stored.notes) == 1 and "job-1" in str(stored.notes[0])
    assert "done" not in str(stored.notes)  # No second copy of Action results.
    assert session.inspect("session:turn/ordered#timeline")["items"]
    assert session.inspect("session:turn/ordered#timeline", query="job-1")["items"]
    assert session.inspect("session:turn/ordered", query="final-answer-marker")["items"]
    assert not session.inspect(
        "session:turn/ordered#timeline", query="final-answer-marker"
    )["items"]


def test_completion_projects_typed_action_business_facts() -> None:
    source = completion(
        "turn_projection",
        ask="write the report",
        actions=(
            SyntheticAction(
                "workspace.compose",
                request={"link": "workspace:report.md"},
                result={"written": True},
                references=("workspace:report.md",),
            ),
            SyntheticAction(
                "web.search",
                status=ActionResultStatus.FAILED,
                failure_reason="provider_unavailable",
            ),
        ),
    )

    record = project_turn_record(
        source,
        day=DAY,
        output=SessionOutputRecord(text="done"),
        status=TurnOutcomeStatus.ANSWERED,
        exhausted=False,
    )

    assert record.ref == "session:turn/turn_projection"
    assert [item.outcome for item in record.actions] == [
        SessionActionOutcome.SUCCESS,
        SessionActionOutcome.FAILED,
    ]
    assert record.actions[0].result == {"written": True}
    assert record.actions[0].references == ("workspace:report.md",)
    assert record.actions[1].failure is not None
    assert record.actions[1].failure.reason == "provider_unavailable"


def test_completion_does_not_reconstruct_actions_from_message_pairing() -> None:
    source = completion(
        "turn_unpaired",
        actions=(SyntheticAction("workspace.read"),),
    )
    broken = replace(
        source,
        trace=SealedTurnTrace(
            turn_id=source.turn_id,
            entries=source.trace.entries[:-1],
            actions=source.trace.actions,
        ),
    )

    record = project_turn_record(
        broken, day=DAY, output=None, exhausted=True, status=TurnOutcomeStatus.EXHAUSTED
    )
    assert len(record.actions) == 1
    assert record.actions[0].outcome is SessionActionOutcome.SUCCESS


@pytest.mark.parametrize(
    "state",
    [
        ExecutionState.CANCELLED,
        ExecutionState.NOT_EXECUTED,
        ExecutionState.UNKNOWN,
    ],
)
def test_completion_preserves_interruption_without_fabricated_result(state) -> None:
    source = completion(
        "turn_interrupted", actions=(SyntheticAction("workspace.compose"),)
    )
    source = replace(
        source,
        trace=replace(
            source.trace,
            actions=(replace(source.trace.actions[0], state=state, result=None),),
        ),
    )
    record = project_turn_record(
        source, day=DAY, output=None, exhausted=False, status=TurnOutcomeStatus.STOPPED
    )
    assert record.actions[0].outcome.value == state.value
    assert record.actions[0].failure is None
    assert record.actions[0].result == {}
