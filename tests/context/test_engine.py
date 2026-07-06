"""Tests for the context engine facade."""

from __future__ import annotations

import pytest

from tinysoul.context import (
    CONTROL_LOAD_BACKGROUND,
    CONTROL_UPDATE_WORKING,
    ContextContractError,
    ContextEngineBuilder,
    TaskPrompt,
    TraceKind,
    build_input_append_signal,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
)
from tinysoul.llm.messages import AssistantMessage, ToolResultMessage
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import CyclePhase, RunLevel, RunScope, Signal, SignalBus

SCOPE = RunScope().push(RunLevel.PHASE, "phase1")


def _engine():
    return (
        ContextEngineBuilder(system_text="You are TinySoul.")
        .with_journal("day journal")
        .add_default_background("home:agent@core", "core rules")
        .add_loadable_background("home:what@x", "entity x")
        .build()
    )


def test_turn_lifecycle_and_compose() -> None:
    engine = _engine()
    with pytest.raises(ContextContractError):
        engine.compose(TaskPrompt(guide="g"))

    turn_id = engine.begin_turn("please help")
    assert turn_id
    with pytest.raises(ContextContractError):
        engine.begin_turn("again")

    stack = engine.compose(TaskPrompt(guide="Phase one."))
    labels = [message.label for message in stack.messages]
    assert labels[0] == "identity"
    assert "user_input" in labels

    summary = engine.end_turn()
    assert summary.turn_id == turn_id
    assert summary.inputs[0]["text"] == "please help"
    assert summary.background_links == ("home:agent@core",)
    assert not engine.turn_active


def test_control_scope_tracks_background_state() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    names = [tool.name for tool in engine.control_scope().tools]
    # home:what@x is loadable; home:agent@core is loaded (and evictable).
    assert CONTROL_LOAD_BACKGROUND in names

    bus = SignalBus()
    normalization = engine.normalize_controls(
        (
            ToolCallRecord(
                id="c1",
                name=CONTROL_LOAD_BACKGROUND,
                arguments={"links": ["home:what@x"]},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=SCOPE,
    )
    for signal in normalization.signals:
        bus.emit(signal)
    results = engine.consume_signals(bus)
    assert results == ()
    assert engine.background.has("home:what@x")


def test_consume_signals_transactional_validation() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    bus = SignalBus()

    normalization = engine.normalize_controls(
        (
            ToolCallRecord(
                id="ok",
                name=CONTROL_UPDATE_WORKING,
                arguments={"set_milestones": [{"key": "m", "content": "made progress"}]},
                kind=ToolKind.CONTROL,
            ),
            ToolCallRecord(
                id="bad",
                name=CONTROL_UPDATE_WORKING,
                arguments={"remove_todos": ["missing"]},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=SCOPE,
    )
    assert len(normalization.signals) == 2
    for signal in normalization.signals:
        bus.emit(signal)

    results = engine.consume_signals(bus)
    assert len(results) == 1
    assert results[0].call_id == "bad"
    assert "Unknown todo key" in results[0].model_feedback
    assert engine.working.milestones()[0].key == "m"


def test_consume_trace_and_input_signals() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    bus = SignalBus()

    bus.emit(
        build_trace_decision_signal(
            AssistantMessage.from_text(
                "choose tools",
                tool_calls=(
                    ToolCallRecord(id="a1", name="workspace.scan", arguments={}),
                ),
            ),
            scope=SCOPE,
            source="loop.phase2",
            cycle_id="c1",
            phase=CyclePhase.PHASE2,
        )
    )
    bus.emit(
        build_trace_action_result_signal(
            ToolResultMessage.from_json(
                call_id="a1",
                tool_name="workspace.scan",
                value={"status": "success"},
            ),
            scope=SCOPE,
            source="loop.phase3",
            cycle_id="c1",
        )
    )
    bus.emit(
        build_trace_phase_note_signal(
            {"feedback": "scope preparation failed"},
            scope=SCOPE,
            source="loop.phase2",
            cycle_id="c1",
            phase=CyclePhase.PHASE2,
        )
    )
    bus.emit(build_input_append_signal("also do this", scope=SCOPE, source="loop.inputs"))
    # Non-context signals stay queued for other consumers.
    bus.emit(Signal(name="loop.control.request", source="loop.inputs", scope=SCOPE))

    results = engine.consume_signals(bus)
    assert results == ()
    kinds = [entry.kind for entry in engine.trace.entries()]
    assert kinds == [
        TraceKind.USER_INPUT,
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
        TraceKind.PHASE_NOTE,
    ]
    assert len(bus) == 1

    merged = engine.merge_pending_inputs()
    assert merged == 1
    assert engine.trace.entries()[-1].kind is TraceKind.USER_INPUT
    assert engine.merge_pending_inputs() == 0


def test_compress_via_engine() -> None:
    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_keep_recent(1)
        .build()
    )
    engine.begin_turn("hi")
    bus = SignalBus()
    for index in range(3):
        bus.emit(
            build_input_append_signal(f"extra {index}", scope=SCOPE, source="loop.inputs")
        )
    engine.consume_signals(bus)
    engine.merge_pending_inputs()

    report = engine.compress()
    assert report.dropped_count == 3
    assert engine.trace.entries()[0].kind is TraceKind.SUMMARY_PLACEHOLDER
