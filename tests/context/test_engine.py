"""Tests for the context engine facade."""

from __future__ import annotations

from typing import cast

import pytest

from tinysoul.context import (
    CONTROL_LOAD_BACKGROUND,
    CONTROL_UPDATE_WORKING,
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_TRACE_APPEND,
    ContextContractError,
    ContextEngineBuilder,
    ContextSignalBatch,
    PromptBlock,
    TaskPrompt,
    TraceKind,
    TurnSummary,
    WorkspaceResource,
    WorkspaceSnapshot,
    build_input_append_signal,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
    build_workspace_sync_signal,
)
from tinysoul.context.signals import build_working_patch_signal
from tinysoul.context.working import WorkingPatch
from tinysoul.llm.messages import AssistantMessage, JsonPart, TextPart, ToolResultMessage
from tinysoul.llm.reasoning import Reasoning
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import CyclePhase, RunLevel, RunScope, Signal, SignalBus

def _scope(turn_id: str) -> RunScope:
    return (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.PHASE, "phase1")
    )


def _engine():
    return (
        ContextEngineBuilder(system_text="You are TinySoul.")
        .with_journal("day journal")
        .add_default_background("home:agent@core", "core rules")
        .add_loadable_background("home:what@x", "entity x")
        .build()
    )


def _prompt(text: str = "next") -> TaskPrompt:
    return TaskPrompt(
        guide_blocks=(
            PromptBlock.from_text("task_prompt:guide:test", "# Task Guide\n" + text),
        )
    )


def test_turn_lifecycle_and_compose() -> None:
    engine = _engine()
    with pytest.raises(ContextContractError):
        engine.compose(_prompt("g"))

    turn_id = engine.begin_turn("please help")
    assert turn_id
    with pytest.raises(ContextContractError):
        engine.begin_turn("again")

    stack = engine.compose(_prompt("Phase one."))
    labels = [message.label for message in stack.messages]
    assert labels[0] == "identity"
    assert labels[1] == "user_input"
    assert labels[2] == "background:journal"

    summary = engine.end_turn()
    assert summary.turn_id == turn_id
    assert summary.inputs[0]["text"] == "please help"
    assert summary.background_links == ("home:agent@core",)
    assert not engine.turn_active


def test_context_batch_and_turn_summary_validate_protocol_fields() -> None:
    with pytest.raises(ContextContractError, match="turn_id"):
        ContextSignalBatch(turn_id="")
    with pytest.raises(ContextContractError, match="Signal"):
        ContextSignalBatch(
            turn_id="turn_1",
            signals=cast(tuple[Signal, ...], (object(),)),
        )
    with pytest.raises(ContextContractError, match="background_links"):
        TurnSummary(
            turn_id="turn_1",
            background_links=("home:agent@core", "home:agent@core"),
        )


def test_control_scope_tracks_background_state() -> None:
    engine = _engine()
    with pytest.raises(ContextContractError):
        engine.control_scope()

    turn_id = engine.begin_turn("hi")
    scope = _scope(turn_id)
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
        scope=scope,
    )
    for signal in normalization.signals:
        bus.emit(signal)
    results = engine.consume_signals(bus)
    assert results == ()
    assert "home:what@x" in engine.background_links()


def test_consume_signals_commits_feasible_valid_changes() -> None:
    engine = _engine()
    turn_id = engine.begin_turn("hi")
    scope = _scope(turn_id)
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
        scope=scope,
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
    scope = _scope(engine.begin_turn("hi"))
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
        scope=scope,
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
        scope=scope,
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
    scope = _scope(engine.begin_turn("hi"))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
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
            scope=scope,
            payload={"kind": "unknown_trace_kind"},
        )
    )

    results = engine.consume_signals(bus)

    assert [result.sequence for result in results] == [1, 2]
    assert results[0].call_id == "background_first"
    assert "Unknown trace append kind" in results[1].model_feedback


def test_consume_signals_validates_background_batch_against_projection() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi"))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
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
            scope=scope,
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
            scope=scope,
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
    scope = _scope(engine.begin_turn("hi"))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
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
    scope = _scope(engine.begin_turn("hi"))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
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


def test_workspace_snapshot_can_be_consumed_from_signal() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi"))
    bus = SignalBus()
    bus.emit(
        build_workspace_sync_signal(
            WorkspaceSnapshot(
                revision=1,
                resources=(
                    WorkspaceResource(
                        link="workspace:doc/a.md",
                        summary="draft notes",
                    ),
                )
            ),
            call_id="workspace_sync",
            scope=scope,
            source="workspace.scan",
        )
    )

    results = engine.consume_signals(bus)

    assert results == ()
    assert engine.working_snapshot()["workspace_resources"] == [
        {"link": "workspace:doc/a.md", "summary": "draft notes"}
    ]
    assert engine.working_snapshot()["workspace_revision"] == 1


def test_context_rejects_workspace_snapshot_from_previous_turn() -> None:
    engine = _engine()
    old_turn = engine.begin_turn("first")
    engine.end_turn()
    engine.begin_turn("second")
    bus = SignalBus()
    bus.emit(
        build_workspace_sync_signal(
            WorkspaceSnapshot(
                revision=1,
                resources=(
                    WorkspaceResource(
                        link="workspace:stale.md",
                        summary="stale",
                    ),
                ),
            ),
            call_id="stale_sync",
            scope=_scope(old_turn),
            source="workspace.scan",
        )
    )

    results = engine.consume_signals(bus)

    assert len(results) == 1
    assert "another Turn" in results[0].model_feedback
    assert engine.working_snapshot()["workspace_resources"] == []
    assert engine.working_snapshot()["workspace_revision"] == -1


def test_context_rejects_conflicting_workspace_snapshot_revision() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi"))
    bus = SignalBus()
    first = WorkspaceSnapshot(
        revision=1,
        resources=(WorkspaceResource(link="workspace:a.md", summary="a"),),
    )
    conflicting = WorkspaceSnapshot(
        revision=1,
        resources=(WorkspaceResource(link="workspace:b.md", summary="b"),),
    )
    bus.emit(
        build_workspace_sync_signal(
            first,
            call_id="sync_1",
            scope=scope,
            source="workspace.scan",
        )
    )
    assert engine.consume_signals(bus) == ()
    bus.emit(
        build_workspace_sync_signal(
            conflicting,
            call_id="sync_2",
            scope=scope,
            source="workspace.scan",
        )
    )

    results = engine.consume_signals(bus)

    assert len(results) == 1
    assert "conflicts" in results[0].model_feedback
    assert engine.working_snapshot()["workspace_resources"] == [
        {"link": "workspace:a.md", "summary": "a"}
    ]


def test_trace_append_rejects_unknown_kind() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi"))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_TRACE_APPEND,
            source="test",
            scope=scope,
            payload={"kind": "unknown_trace_kind"},
        )
    )

    results = engine.consume_signals(bus)

    assert len(results) == 1
    assert "Unknown trace append kind" in results[0].model_feedback


def test_consume_trace_and_input_signals() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi"))
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
            scope=scope,
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
            scope=scope,
            source="loop.phase3",
            cycle_id="c1",
        )
    )
    bus.emit(
        build_trace_phase_note_signal(
            {"feedback": "scope preparation failed"},
            scope=scope,
            source="loop.phase2",
            cycle_id="c1",
            phase=CyclePhase.PHASE2,
        )
    )
    bus.emit(build_input_append_signal("also do this", scope=scope, source="app.inputs"))
    # Non-context signals stay queued for other consumers.
    bus.emit(Signal(name="loop.control.request", source="app.inputs", scope=scope))

    results = engine.consume_signals(bus)
    assert results == ()
    assert engine.trace_kinds() == (
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
        TraceKind.PHASE_NOTE,
    )
    assert len(bus) == 1
    stack = engine.compose(_prompt("next"))
    decision = next(message for message in stack.messages if message.label == "decision")
    assert isinstance(decision, AssistantMessage)
    assert isinstance(decision.parts[1], JsonPart)
    assert decision.reasoning is not None
    assert decision.reasoning.summary == "scan plan"

    merged = engine.merge_pending_inputs()
    assert merged == 1
    stack = engine.compose(_prompt("next"))
    assert [message.label for message in stack.messages].count("user_input") == 2
    assert engine.trace_kinds() == (
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
        TraceKind.PHASE_NOTE,
    )
    assert engine.merge_pending_inputs() == 0


def test_compress_via_engine() -> None:
    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_trace_heap(
            chunk_max_chars=12000,
            branch_factor=4,
            min_hot_entries=0,
        )
        .build()
    )
    turn_id = engine.begin_turn("hi")
    scope = _scope(turn_id)
    bus = SignalBus()
    for index in range(3):
        bus.emit(
            build_trace_phase_note_signal(
                {"note": f"extra {index}"},
                scope=scope,
                source="test",
                cycle_id="c1",
            )
        )
    engine.consume_signals(bus)

    report = engine.compress()
    assert report.changed is True
    assert report.compacted_count == 3
    assert engine.trace_kinds() == (TraceKind.PHASE_NOTE,) * 3
    assert engine.inspect_trace(f"turn:trace@{turn_id}")["roots"]


def test_abort_turn_discards_active_state() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    assert engine.turn_active is True

    engine.abort_turn()

    assert engine.turn_active is False
    with pytest.raises(ContextContractError):
        engine.working_snapshot()
    engine.begin_turn("new turn")
    assert engine.turn_active is True


def test_engine_exposes_snapshots_not_mutable_context_holders() -> None:
    engine = _engine()
    engine.begin_turn("hi")

    assert not hasattr(engine, "background")
    assert not hasattr(engine, "working")
    assert not hasattr(engine, "trace")
    assert engine.working_snapshot()["todos"] == []


def test_builder_validates_background_configuration() -> None:
    with pytest.raises(ContextContractError):
        ContextEngineBuilder(system_text="sys").with_trace_heap(
            chunk_max_chars=1,
            branch_factor=1,
            min_hot_entries=0,
        )
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
            .add_loadable_background("home:what@x", "a")
            .add_loadable_background("home:what@x", "b")
        )
