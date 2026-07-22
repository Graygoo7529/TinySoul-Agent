"""Tests for context state holders."""

from __future__ import annotations

import pytest

from tinysoul.context.background import (
    BackgroundContext,
    BackgroundEntry,
    BackgroundPatch,
    BackgroundSource,
)
from tinysoul.context.errors import ContextContractError
from tinysoul.context.trace import PendingInputs, TraceKind, TurnTraceHeap
from tinysoul.context.working import (
    Milestone,
    TodoItem,
    TodoStatus,
    WorkingContext,
    WorkingPatch,
    WorkspaceResource,
    WorkspaceSnapshot,
)
from tinysoul.llm.messages import AssistantMessage, JsonPart, ToolResultMessage, UserMessage
from tinysoul.runtime import CyclePhase


def test_background_load_evict_and_render() -> None:
    background = BackgroundContext(journal="today so far")
    background.load(
        BackgroundEntry(
            link="home:what@concept/tinysoul",
            content="TinySoul is an agent.",
        )
    )
    assert background.has("home:what@concept/tinysoul")
    messages = background.render_messages()
    assert isinstance(messages[0], UserMessage)
    assert messages[0].label == "background:journal"
    assert messages[1].label == "background:home:what@concept/tinysoul"

    background.evict("home:what@concept/tinysoul")
    assert not background.has("home:what@concept/tinysoul")
    with pytest.raises(ContextContractError):
        background.evict("home:what@concept/tinysoul")


def test_background_load_replaces_same_link() -> None:
    background = BackgroundContext()
    background.load(BackgroundEntry(link="home:why@q", content="old"))
    background.load(
        BackgroundEntry(
            link="home:why@q",
            content="new",
            source=BackgroundSource.PHASE1,
        )
    )
    entries = background.entries()
    assert len(entries) == 1
    assert entries[0].content == "new"
    assert entries[0].source is BackgroundSource.PHASE1


def test_background_patch_sequence_validates_projected_loaded_links() -> None:
    background = BackgroundContext()
    problems = background.check_patch_sequence(
        (
            BackgroundPatch(load_links=("home:what@concept/x",)),
            BackgroundPatch(evict_links=("home:what@concept/x",)),
            BackgroundPatch(evict_links=("home:what@concept/x",)),
        ),
        loadable_links=("home:what@concept/x",),
        evictable_links=("home:what@concept/x",),
    )

    assert problems[0] == ""
    assert problems[1] == ""
    assert "not loaded" in problems[2]


def test_background_patch_rejects_load_evict_conflict() -> None:
    background = BackgroundContext()
    problem = background.check_patch(
        BackgroundPatch(
            load_links=("home:what@concept/x",),
            evict_links=("home:what@concept/x",),
        ),
        loadable_links=("home:what@concept/x",),
        evictable_links=("home:what@concept/x",),
    )

    assert "cannot load and evict" in problem


def test_background_patch_rejects_duplicate_links() -> None:
    background = BackgroundContext()
    problem = background.check_patch(
        BackgroundPatch(
            load_links=("home:what@concept/x", "home:what@concept/x")
        ),
        loadable_links=("home:what@concept/x",),
        evictable_links=("home:what@concept/x",),
    )

    assert "duplicate load link" in problem


def test_working_patch_check_and_apply() -> None:
    working = WorkingContext()
    patch = WorkingPatch(
        set_milestones=(Milestone(key="goal", content="ship context module"),),
        set_todos=(TodoItem(key="t1", content="write tests"),),
    )
    assert working.check_patch(patch) == ""
    working.apply_patch(patch)
    assert working.milestones()[0].content == "ship context module"
    assert working.todos()[0].status is TodoStatus.PENDING
    working.apply_workspace_snapshot(
        WorkspaceSnapshot(
            revision=1,
            resources=(
                WorkspaceResource(link="workspace:doc/a.md", summary="notes"),
            ),
        )
    )
    assert working.workspace_revision == 1
    assert working.resources()[0].link == "workspace:doc/a.md"

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


def test_working_message_is_anchored_without_changing_persisted_state() -> None:
    working = WorkingContext()
    trace = TurnTraceHeap(turn_id="turn_anchor")
    trace.append_phase_note("observed")

    message = working.render_messages(trace_anchor=trace.anchor())[0]
    part = message.parts[0]

    assert isinstance(part, JsonPart)
    assert part.value["as_of_trace"] == {
        "ref": "turn:trace@turn_anchor",
        "canonical_revision": 1,
    }
    assert "as_of_trace" not in working.to_json()


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
    trace = TurnTraceHeap()
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
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
        TraceKind.PHASE_NOTE,
    ]
    assert len(trace.render_messages()) == 3


def test_trace_compaction_keeps_canonical_entries_and_exposes_heap_head() -> None:
    trace = TurnTraceHeap(min_hot_entries=2)
    for index in range(6):
        trace.append_phase_note(f"note {index}")
    anchor = trace.anchor()
    report = trace.compact(required_chars=1)
    assert report.changed is True
    assert report.compacted_count == 4
    assert len(trace.entries()) == 6
    assert len(trace.hot_entries()) == 2
    assert trace.render_messages()[0].label == "trace_heap_head"
    assert trace.anchor() == anchor

    again = trace.compact(required_chars=1)
    assert again.changed is False
    assert again.compacted_count == 0


def test_trace_compaction_builds_recallable_leaf_nodes() -> None:
    trace = TurnTraceHeap(turn_id="turn_test", min_hot_entries=1)
    for index in range(4):
        trace.append_phase_note(f"note {index}")
    report = trace.compact(required_chars=1)
    assert report.compacted_count == 3
    head = trace.inspect(trace.head_ref())
    assert head["canonical_revision"] == 4
    roots = head["roots"]
    assert isinstance(roots, list)
    assert roots
    root = roots[0]
    assert isinstance(root, dict)
    ref = root["ref"]
    assert isinstance(ref, str)
    recalled = trace.recall(ref, max_chars=1000)
    assert [entry.kind for entry in recalled.entries] == [TraceKind.PHASE_NOTE] * 3
    assert recalled.next_cursor is None


def test_trace_recall_pages_through_an_immutable_leaf() -> None:
    trace = TurnTraceHeap(turn_id="turn_page", min_hot_entries=0)
    for index in range(4):
        trace.append_phase_note(f"note {index}" + "x" * 30)
    trace.compact(required_chars=1)
    head = trace.inspect(trace.head_ref())
    roots = head["roots"]
    assert isinstance(roots, list)
    root = roots[0]
    assert isinstance(root, dict)
    ref = root["ref"]
    assert isinstance(ref, str)

    first = trace.recall(ref, max_chars=40)
    assert len(first.entries) == 1
    assert first.next_cursor == 1
    second = trace.recall(ref, max_chars=1000, cursor=first.next_cursor)
    assert len(second.entries) == 3
    assert second.next_cursor is None


def test_trace_compaction_does_not_split_cycle_at_hot_boundary() -> None:
    trace = TurnTraceHeap(min_hot_entries=2)
    for index in range(3):
        trace.append_phase_note(f"cycle one {index}", cycle_id="cycle_1")
    trace.append_phase_note("cycle two", cycle_id="cycle_2")

    report = trace.compact(required_chars=1)

    assert report.changed is False
    assert report.compacted_count == 0
    assert len(trace.hot_entries()) == 4


def test_trace_recall_overlay_folds_back_to_origin_pointer() -> None:
    trace = TurnTraceHeap()
    full = ToolResultMessage.from_json(
        call_id="recall_1",
        tool_name="session.history.recall",
        value={"detail": "x" * 200},
    )
    compact = ToolResultMessage.from_json(
        call_id="recall_1",
        tool_name="session.history.recall",
        value={"origin_ref": "session:turn/old", "folded": True},
    )
    trace.append_action_result(
        full,
        compact_message=compact,
        origin_refs=("session:turn/old",),
    )

    anchor = trace.anchor()
    assert trace.render_messages()[0] == full
    report = trace.compact(required_chars=0)
    assert report.folded_overlay_count == 1
    assert trace.render_messages()[0] == compact
    assert trace.entries()[0].origin_refs == ("session:turn/old",)
    assert trace.anchor() == anchor


def test_pending_inputs_merge_lifecycle() -> None:
    inputs = PendingInputs()
    first = inputs.add("initial", merged=True)
    second = inputs.add("appended")
    assert [item.input_id for item in inputs.unmerged()] == [second.input_id]

    inputs.mark_merged((second.input_id,))
    assert inputs.unmerged() == ()
    assert len(inputs.all()) == 2
    assert first.merged is True
    rendered = inputs.render_messages()
    assert [message.label for message in rendered] == ["user_input", "user_input"]
    assert all(isinstance(message, UserMessage) for message in rendered)

    with pytest.raises(ContextContractError):
        inputs.mark_merged(("missing",))
