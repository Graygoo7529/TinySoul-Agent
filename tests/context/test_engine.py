"""Tests for the context engine facade."""

from __future__ import annotations

import pytest

from tinysoul.context import (
    CONTROL_LOAD_BACKGROUND,
    CONTROL_UPDATE_WORKING,
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_TRACE_APPEND,
    ContextContractError,
    ContextEngineBuilder,
    TaskPrompt,
    TraceKind,
    build_input_append_signal,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
)
from tinysoul.context.signals import build_working_patch_signal
from tinysoul.context.working import WorkingPatch, WorkspaceResource
from tinysoul.llm.messages import AssistantMessage, JsonPart, TextPart, ToolResultMessage
from tinysoul.llm.reasoning import Reasoning
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
    with pytest.raises(ContextContractError):
        engine.control_scope()

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
    assert "home:what@x" in engine.background_links()


def test_consume_signals_commits_feasible_valid_changes() -> None:
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
    assert engine.working_snapshot()["milestones"][0]["key"] == "m"


def test_consume_signals_validates_working_batch_against_projection() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    bus = SignalBus()

    setup = engine.normalize_controls(
        (
            ToolCallRecord(
                id="set",
                name=CONTROL_UPDATE_WORKING,
                arguments={"set_todos": [{"key": "t1", "content": "write"}]},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=SCOPE,
    )
    for signal in setup.signals:
        bus.emit(signal)
    assert engine.consume_signals(bus) == ()

    batch = engine.normalize_controls(
        (
            ToolCallRecord(
                id="remove_1",
                name=CONTROL_UPDATE_WORKING,
                arguments={"remove_todos": ["t1"]},
                kind=ToolKind.CONTROL,
            ),
            ToolCallRecord(
                id="remove_2",
                name=CONTROL_UPDATE_WORKING,
                arguments={"remove_todos": ["t1"]},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=SCOPE,
    )
    for signal in batch.signals:
        bus.emit(signal)

    results = engine.consume_signals(bus)
    assert len(results) == 1
    assert results[0].call_id == "remove_2"
    assert "Unknown todo key" in results[0].model_feedback
    assert engine.working_snapshot()["todos"] == []


def test_consume_signal_results_preserve_signal_order() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=SCOPE,
            payload={
                "call_id": "background_first",
                "load_links": ["missing"],
                "evict_links": [],
            },
        )
    )
    bus.emit(
        Signal(
            name=SIGNAL_TRACE_APPEND,
            source="test",
            scope=SCOPE,
            payload={"kind": "unknown_trace_kind"},
        )
    )

    results = engine.consume_signals(bus)

    assert [result.sequence for result in results] == [1, 2]
    assert results[0].call_id == "background_first"
    assert "Unknown trace append kind" in results[1].model_feedback


def test_consume_signals_validates_background_batch_against_projection() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=SCOPE,
            payload={
                "call_id": "load",
                "load_links": ["home:what@x"],
                "evict_links": [],
            },
        )
    )
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=SCOPE,
            payload={
                "call_id": "evict",
                "load_links": [],
                "evict_links": ["home:what@x"],
            },
        )
    )
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=SCOPE,
            payload={
                "call_id": "evict_again",
                "load_links": [],
                "evict_links": ["home:what@x"],
            },
        )
    )

    results = engine.consume_signals(bus)
    assert len(results) == 1
    assert results[0].call_id == "evict_again"
    assert "not loaded" in results[0].model_feedback
    assert "home:what@x" not in engine.background_links()


def test_background_signal_rejects_load_evict_conflict() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=SCOPE,
            payload={
                "call_id": "conflict",
                "load_links": ["home:what@x"],
                "evict_links": ["home:what@x"],
            },
        )
    )

    results = engine.consume_signals(bus)
    assert len(results) == 1
    assert results[0].call_id == "conflict"
    assert "cannot load and evict" in results[0].model_feedback
    assert "home:what@x" not in engine.background_links()


def test_background_signal_treats_loaded_link_load_as_noop() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=SCOPE,
            payload={
                "call_id": "reload_default",
                "load_links": ["home:agent@core"],
                "evict_links": [],
            },
        )
    )

    results = engine.consume_signals(bus)

    assert results == ()
    assert engine.background_links() == ("home:agent@core",)


def test_working_resource_patch_can_be_consumed_from_signal() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    bus = SignalBus()
    bus.emit(
        build_working_patch_signal(
            WorkingPatch(
                set_resources=(
                    WorkspaceResource(
                        link="workspace:doc/a.md",
                        summary="draft notes",
                    ),
                )
            ),
            call_id="workspace_sync",
            scope=SCOPE,
            source="workspace.sync",
        )
    )

    results = engine.consume_signals(bus)

    assert results == ()
    assert engine.working_snapshot()["workspace_resources"] == [
        {"link": "workspace:doc/a.md", "summary": "draft notes"}
    ]


def test_trace_append_rejects_unknown_kind() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_TRACE_APPEND,
            source="test",
            scope=SCOPE,
            payload={"kind": "unknown_trace_kind"},
        )
    )

    results = engine.consume_signals(bus)

    assert len(results) == 1
    assert "Unknown trace append kind" in results[0].model_feedback


def test_consume_trace_and_input_signals() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    bus = SignalBus()

    bus.emit(
        build_trace_decision_signal(
            AssistantMessage.from_parts(
                TextPart("choose tools"),
                JsonPart({"hint": "scan first"}),
                reasoning=Reasoning(content="private trace", summary="scan plan"),
                tool_calls=(
                    ToolCallRecord(id="a1", name="workspace.scan", arguments={}),
                ),
                label="decision",
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
    bus.emit(build_input_append_signal("also do this", scope=SCOPE, source="app.inputs"))
    # Non-context signals stay queued for other consumers.
    bus.emit(Signal(name="loop.control.request", source="app.inputs", scope=SCOPE))

    results = engine.consume_signals(bus)
    assert results == ()
    assert engine.trace_kinds() == (
        TraceKind.USER_INPUT,
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
        TraceKind.PHASE_NOTE,
    )
    assert len(bus) == 1
    stack = engine.compose(TaskPrompt(guide="next"))
    decision = next(message for message in stack.messages if message.label == "decision")
    assert isinstance(decision, AssistantMessage)
    assert isinstance(decision.parts[1], JsonPart)
    assert decision.reasoning is not None
    assert decision.reasoning.summary == "scan plan"

    merged = engine.merge_pending_inputs()
    assert merged == 1
    assert engine.trace_kinds()[-1] is TraceKind.USER_INPUT
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
            build_input_append_signal(f"extra {index}", scope=SCOPE, source="app.inputs")
        )
    engine.consume_signals(bus)
    engine.merge_pending_inputs()

    report = engine.compress()
    assert report.changed is True
    assert report.dropped_count == 3
    assert engine.trace_kinds()[0] is TraceKind.SUMMARY_PLACEHOLDER


def test_engine_exposes_snapshots_not_mutable_context_holders() -> None:
    engine = _engine()
    engine.begin_turn("hi")

    assert not hasattr(engine, "background")
    assert not hasattr(engine, "working")
    assert not hasattr(engine, "trace")
    assert engine.working_snapshot()["todos"] == []


def test_builder_validates_background_configuration() -> None:
    with pytest.raises(ContextContractError):
        ContextEngineBuilder(system_text="sys").with_keep_recent(-1)
    with pytest.raises(ContextContractError):
        ContextEngineBuilder(system_text="sys").with_budget_max_chars(0)
    with pytest.raises(ContextContractError):
        ContextEngineBuilder(system_text="sys").add_default_background("", "content")
    with pytest.raises(ContextContractError):
        (
            ContextEngineBuilder(system_text="sys")
            .add_default_background("home:agent@core", "a")
            .add_default_background("home:agent@core", "a")
        )
    with pytest.raises(ContextContractError):
        (
            ContextEngineBuilder(system_text="sys")
            .add_default_background("home:agent@core", "a")
            .add_loadable_background("home:agent@core", "b")
        )
