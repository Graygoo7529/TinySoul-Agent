"""Tests for context state holders."""

from __future__ import annotations

import pytest

from tinysoul.context import (
    BackgroundContext,
    BackgroundEntry,
    BackgroundPatch,
    BackgroundSource,
    ContextContractError,
    Milestone,
    PendingInputs,
    TodoItem,
    TodoStatus,
    TraceKind,
    TurnTraceContext,
    WorkingContext,
    WorkingPatch,
    WorkspaceResource,
)
from tinysoul.llm.messages import AssistantMessage, JsonPart, SystemMessage, ToolResultMessage
from tinysoul.runtime import CyclePhase


def test_background_load_evict_and_render() -> None:
    background = BackgroundContext(journal="today so far")
    background.load(BackgroundEntry(link="home:what@tinysoul", content="TinySoul is an agent."))
    assert background.has("home:what@tinysoul")
    messages = background.render_messages()
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].label == "background:journal"
    assert messages[1].label == "background:home:what@tinysoul"

    background.evict("home:what@tinysoul")
    assert not background.has("home:what@tinysoul")
    with pytest.raises(ContextContractError):
        background.evict("home:what@tinysoul")


def test_background_load_replaces_same_link() -> None:
    background = BackgroundContext()
    background.load(BackgroundEntry(link="home:why@q", content="old"))
    background.load(
        BackgroundEntry(link="home:why@q", content="new", source=BackgroundSource.PHASE1)
    )
    entries = background.entries()
    assert len(entries) == 1
    assert entries[0].content == "new"
    assert entries[0].source is BackgroundSource.PHASE1


def test_background_patch_sequence_validates_projected_loaded_links() -> None:
    background = BackgroundContext()
    problems = background.check_patch_sequence(
        (
            BackgroundPatch(load_links=("home:what@x",)),
            BackgroundPatch(evict_links=("home:what@x",)),
            BackgroundPatch(evict_links=("home:what@x",)),
        ),
        loadable_links=("home:what@x",),
    )

    assert problems[0] == ""
    assert problems[1] == ""
    assert "not loaded" in problems[2]


def test_background_patch_rejects_load_evict_conflict() -> None:
    background = BackgroundContext()
    problem = background.check_patch(
        BackgroundPatch(
            load_links=("home:what@x",),
            evict_links=("home:what@x",),
        ),
        loadable_links=("home:what@x",),
    )

    assert "cannot load and evict" in problem


def test_background_patch_rejects_duplicate_links() -> None:
    background = BackgroundContext()
    problem = background.check_patch(
        BackgroundPatch(load_links=("home:what@x", "home:what@x")),
        loadable_links=("home:what@x",),
    )

    assert "duplicate load link" in problem


def test_working_patch_check_and_apply() -> None:
    working = WorkingContext()
    patch = WorkingPatch(
        set_milestones=(Milestone(key="goal", content="ship context module"),),
        set_todos=(TodoItem(key="t1", content="write tests"),),
        set_resources=(WorkspaceResource(link="workspace:doc/a.md", summary="notes"),),
    )
    assert working.check_patch(patch) == ""
    working.apply_patch(patch)
    assert working.milestones()[0].content == "ship context module"
    assert working.todos()[0].status is TodoStatus.PENDING

    removal = WorkingPatch(remove_todos=("t1",))
    working.apply_patch(removal)
    assert working.todos() == ()

    bad = WorkingPatch(remove_milestones=("missing",))
    assert "Unknown milestone key" in working.check_patch(bad)
    assert "no operations" in working.check_patch(WorkingPatch())


def test_working_patch_rejects_conflicting_and_duplicate_operations() -> None:
    working = WorkingContext()
    conflict = WorkingPatch(
        set_todos=(TodoItem(key="t1", content="write"),),
        remove_todos=("t1",),
    )
    duplicate = WorkingPatch(remove_todos=("t1", "t1"))

    assert "cannot set and remove" in working.check_patch(conflict)
    assert "duplicate todo remove key" in working.check_patch(duplicate)


def test_working_patch_sequence_validates_projected_state() -> None:
    working = WorkingContext()
    problems = working.check_patch_sequence(
        (
            WorkingPatch(set_todos=(TodoItem(key="t1", content="write"),)),
            WorkingPatch(remove_todos=("t1",)),
            WorkingPatch(remove_todos=("t1",)),
        )
    )

    assert problems[0] == ""
    assert problems[1] == ""
    assert "Unknown todo key" in problems[2]


def test_trace_appends_and_render_order() -> None:
    trace = TurnTraceContext()
    trace.append_user_input("hello")
    trace.append_decision(
        AssistantMessage.from_text("thinking"),
        cycle_id="c1",
        phase=CyclePhase.PHASE2,
    )
    trace.append_action_result(
        ToolResultMessage.from_json(
            call_id="call_1",
            tool_name="core.answer",
            value={"status": "success"},
        ),
        cycle_id="c1",
    )
    trace.append_phase_note({"feedback": "scope failed"}, cycle_id="c1")
    kinds = [entry.kind for entry in trace.entries()]
    assert kinds == [
        TraceKind.USER_INPUT,
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
        TraceKind.PHASE_NOTE,
    ]
    assert len(trace.render_messages()) == 4


def test_trace_compression_keeps_recent_and_adds_placeholder() -> None:
    trace = TurnTraceContext()
    for index in range(6):
        trace.append_user_input(f"input {index}")
    report = trace.compress_oldest(keep_recent=2)
    assert report.changed is True
    assert report.dropped_count == 4
    entries = trace.entries()
    assert entries[0].kind is TraceKind.SUMMARY_PLACEHOLDER
    assert len(entries) == 3

    # A second pass with nothing else to drop reports no progress.
    again = trace.compress_oldest(keep_recent=2)
    assert again.changed is False
    assert again.dropped_count == 0


def test_trace_compression_merges_existing_placeholder() -> None:
    trace = TurnTraceContext()
    for index in range(4):
        trace.append_user_input(f"input {index}")
    first = trace.compress_oldest(keep_recent=1)
    assert first.dropped_count == 3
    for index in range(2):
        trace.append_user_input(f"new {index}")

    second = trace.compress_oldest(keep_recent=1)
    assert second.changed is True
    assert second.dropped_count == 2
    entries = trace.entries()
    assert [entry.kind for entry in entries].count(TraceKind.SUMMARY_PLACEHOLDER) == 1
    placeholder = entries[0].message.parts[0]
    assert isinstance(placeholder, JsonPart)
    assert placeholder.value["dropped_count"] == 5


def test_pending_inputs_merge_lifecycle() -> None:
    inputs = PendingInputs()
    first = inputs.add("initial", merged=True)
    second = inputs.add("appended")
    assert [item.input_id for item in inputs.unmerged()] == [second.input_id]

    inputs.mark_merged((second.input_id,))
    assert inputs.unmerged() == ()
    assert len(inputs.all()) == 2
    assert first.merged is True

    with pytest.raises(ContextContractError):
        inputs.mark_merged(("missing",))
