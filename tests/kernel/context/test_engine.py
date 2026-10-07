"""Tests for the context engine facade."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from threading import Event
from typing import cast

import pytest

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.json import to_json_object
from tinysoul.kernel.context import (
    CONTROL_LOAD_BACKGROUND,
    CONTROL_REMOVE_TODO,
    CONTROL_SET_MILESTONE,
    CONTROL_SET_TODO,
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_TRACE_APPEND,
    BackgroundCatalog,
    BackgroundCatalogItem,
    ContextContractError,
    ContextEngineBuilder,
    ContextInvariantError,
    ContextSignalBatch,
    ContextTurnCompletion,
    ContextTurnInput,
    PromptBlock,
    TaskPrompt,
    build_input_append_signal,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
)
from tinysoul.kernel.context.background import heap_segment_registration
from tinysoul.kernel.context.builtin.trace import SealedTurnTrace, TraceKind
from tinysoul.kernel.context.builtin.working import Milestone, WorkingPatch
from tinysoul.kernel.context.providers import BackgroundEntryProvider
from tinysoul.kernel.context.segments import (
    SegmentCapability,
    SegmentDescriptor,
    SegmentShape,
    SegmentSlot,
)
from tinysoul.kernel.context.signals import build_working_patch_signal
from tinysoul.llm.protocol.messages import (
    AssistantMessage,
    JsonPart,
    TextPart,
    ToolResultMessage,
)
from tinysoul.llm.protocol.reasoning import Reasoning
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.runtime import (
    CyclePhase,
    ObservationEvent,
    ObservationLevel,
    RunLevel,
    RunScope,
    Signal,
    SignalBus,
)


@dataclass
class RecordingObservations:
    events: list[ObservationEvent] = field(default_factory=list)

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)


def _scope(turn_id: str) -> RunScope:
    return (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.PHASE, "phase1")
    )


@dataclass
class TextSource:
    texts: dict[str, str] = field(
        default_factory=lambda: {
            "home:top/agent/AGENT": "core rules",
            "home:top/skills/x": "entity x",
        }
    )

    async def catalog(self, active_day: date) -> BackgroundCatalog:
        return BackgroundCatalog(
            owner="home",
            default_refs=("home:top/agent/AGENT",),
            loadable_refs=tuple(self.texts),
            evictable_default_refs=("home:top/agent/AGENT",),
        )

    async def load(self, ref: str, active_day: date) -> str:
        return self.texts[ref]


def _registration(source: BackgroundEntryProvider):
    return heap_segment_registration(
        SegmentDescriptor(
            "home",
            "home",
            SegmentSlot.BACKGROUND,
            40,
            shape=SegmentShape.HEAP,
            capabilities=frozenset(
                {SegmentCapability.SELECT, SegmentCapability.RECLAIM}
            ),
        ),
        source,
        signal_name="context.home.update",
    )


def _engine():
    return (
        ContextEngineBuilder(system_text="You are TinySoul.")
        .with_journal("day journal")
        .with_segment(_registration(TextSource()))
        .build()
    )


def _prompt(text: str = "next") -> TaskPrompt:
    return TaskPrompt(
        guide_blocks=(
            PromptBlock.from_text("task_prompt:guide:test", "# Task Guide\n" + text),
        )
    )


async def test_background_prepare_failure_installs_neither_catalog_nor_entries() -> (
    None
):
    class Provider:
        async def catalog(self, active_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home",
                loadable_refs=("home:top/agent/AGENT",),
                default_refs=("home:top/agent/AGENT",),
                items=(
                    BackgroundCatalogItem(
                        ref="home:top/agent/AGENT", title="Rules", description="Rules"
                    ),
                ),
            )

        async def load(self, ref: str, active_day: date) -> str:
            return ""  # A broken owner response after the catalog was prepared.

    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_segment(_registration(Provider()))
        .build()
    )
    engine.begin_turn("question", turn_id="2026-10-06/167")
    with pytest.raises(ContextInvariantError, match="content must be non-empty"):
        await engine.open_segments(date(2026, 9, 15))
    with pytest.raises(ContextContractError, match="opened"):
        engine.compose(_prompt())
    assert engine.background_refs() == ()


async def test_installed_overview_exposes_owner_navigation_root_for_inspect() -> None:
    engine = _engine()
    turn_id = engine.begin_turn("inspect roots", turn_id="2026-10-06/177")
    await engine.open_segments(date(2026, 9, 15))

    overview = engine.installed_overview()
    trace = next(item for item in overview["segments"] if item["id"] == "trace")
    assert trace["root_refs"] == [f"turn:trace/{turn_id}"]
    page = (await engine.inspect(trace["root_refs"][0])).to_json()
    assert page["ref"] == trace["root_refs"][0]


async def test_cancelled_background_prepare_joins_read_without_installing_view() -> (
    None
):
    entered = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    class Provider:
        async def catalog(self, active_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home",
                loadable_refs=("home:top/agent/AGENT",),
                default_refs=("home:top/agent/AGENT",),
            )

        async def load(self, ref: str, active_day: date) -> str:
            loop.call_soon_threadsafe(entered.set)
            operations = JoinedOperations()
            assert await operations.run(lambda: release.wait(timeout=5))
            operations.check_cancelled()
            return "Rules"

    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_segment(_registration(Provider()))
        .build()
    )
    engine.begin_turn("question", turn_id="2026-10-06/214")
    preparing = asyncio.create_task(engine.open_segments(date(2026, 9, 15)))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        preparing.cancel()
        await asyncio.sleep(0)
        assert not preparing.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await preparing
    with pytest.raises(ContextContractError, match="opened"):
        engine.compose(_prompt())


async def test_background_batch_retry_keeps_new_input_outside_prepared_batch() -> None:
    entered = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    class Loader:
        calls = 0

        async def catalog(self, active_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home", loadable_refs=("home:top/skills/guide",)
            )

        async def load(self, ref: str, active_day: date) -> str:
            self.calls += 1
            if self.calls == 1:
                loop.call_soon_threadsafe(entered.set)
                operations = JoinedOperations()
                assert await operations.run(lambda: release.wait(timeout=5))
                operations.check_cancelled()
                raise ContextInvariantError("Background temporarily unavailable")
            return "Loaded details"

    loader = Loader()
    observations = RecordingObservations()
    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_observations(observations)
        .with_segment(_registration(loader))
        .build()
    )
    turn_id = engine.begin_turn("question", turn_id="2026-10-06/260")
    await engine.open_segments(date(2026, 7, 14))
    scope = _scope(turn_id)
    bus = SignalBus()
    normalized = engine.normalize_controls(
        (
            ToolCallRecord(
                id="milestone",
                name=CONTROL_SET_MILESTONE,
                arguments={"key": "m", "content": "Prepared fact"},
                kind=ToolKind.CONTROL,
            ),
            ToolCallRecord(
                id="background",
                name=CONTROL_LOAD_BACKGROUND,
                arguments={"refs": ["home:top/skills/guide"]},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=scope,
    )
    assert not normalized.results
    for signal in normalized.signals:
        bus.emit(signal)
    batch = engine.take_signal_batch(bus)
    before = engine.working_snapshot()
    consuming = asyncio.create_task(engine.consume_signal_batch(batch))
    pending = build_input_append_signal("later input", scope=scope, source="test")
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        bus.emit(pending)
        assert engine.working_snapshot() == before
    finally:
        release.set()
    with pytest.raises(ContextInvariantError):
        await consuming
    assert engine.working_snapshot() == before
    assert not [
        event
        for event in observations.events
        if event.name == "context.control.applied"
    ]
    assert await engine.consume_signal_batch(batch) == ()
    assert [
        event.payload["call_id"]
        for event in observations.events
        if event.name == "context.control.applied"
    ] == ["milestone", "background"]
    assert engine.working_snapshot()["milestones"]
    assert engine.background_refs() == ("home:top/skills/guide",)
    assert bus.peek() == (pending,)
    assert loader.calls == 2
    assert await engine.consume_signals(bus) == ()
    assert [item.text for item in engine.end_turn().inputs] == [
        "question",
        "later input",
    ]


async def test_turn_lifecycle_and_compose() -> None:
    engine = _engine()
    with pytest.raises(ContextContractError):
        engine.compose(_prompt("g"))

    turn_id = engine.begin_turn("please help", turn_id="2026-10-06/324")
    await engine.open_segments(date(2026, 7, 14))
    assert turn_id
    with pytest.raises(ContextContractError):
        engine.begin_turn("again", turn_id="2026-10-06/328")
    await engine.open_segments(date(2026, 7, 14))

    stack = engine.compose(_prompt("Phase one."))
    labels = [message.label for message in stack.messages]
    assert labels[0] == "identity"
    assert labels[1] == "user_input"
    assert labels[2] == "background:journal"

    summary = engine.end_turn()
    assert summary.turn_id == turn_id
    assert summary.inputs[0].text == "please help"
    assert summary.background_refs == ("home:top/agent/AGENT",)
    assert not engine.turn_active


async def test_foldable_action_result_persists_only_compact_trace_payload() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("read workspace", turn_id="2026-10-06/346"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        build_trace_action_result_signal(
            ToolResultMessage.from_json(
                call_id="read_1",
                tool_name="workspace.read",
                value={"ref": "workspace:a.md", "text": "sensitive body"},
            ),
            scope=scope,
            source="loop.phase3",
            cycle_id="cycle_1",
            origin_refs=("workspace:a.md",),
            canonical_message=ToolResultMessage.from_json(
                call_id="read_1",
                tool_name="workspace.read",
                value={
                    "action": "workspace.read",
                    "status": "success",
                    "stage": "execute",
                    "payload": {"ref": "workspace:a.md", "folded": True},
                },
            ),
        )
    )

    assert await engine.consume_signals(bus) == ()
    visible = next(
        message
        for message in engine.compose(_prompt()).messages
        if isinstance(message, ToolResultMessage)
    )
    assert isinstance(visible.parts[0], JsonPart)
    assert visible.parts[0].value["text"] == "sensitive body"

    summary = engine.end_turn()
    entry = next(
        entry
        for entry in summary.trace.entries
        if entry.kind is TraceKind.ACTION_RESULT
    )
    trace_message = entry.message
    assert isinstance(trace_message, ToolResultMessage)
    content = trace_message.parts
    assert isinstance(content[0], JsonPart)
    assert content[0].value["payload"] == {
        "ref": "workspace:a.md",
        "folded": True,
    }
    assert entry.origin_refs == ("workspace:a.md",)


def test_context_batch_and_turn_summary_validate_protocol_fields() -> None:
    with pytest.raises(ContextContractError, match="turn_id"):
        ContextSignalBatch(turn_id="")
    with pytest.raises(ContextContractError, match="Signal"):
        ContextSignalBatch(
            turn_id="2026-10-06/1000",
            signals=cast(tuple[Signal, ...], (object(),)),
        )
    with pytest.raises(ContextContractError, match="background_refs"):
        ContextTurnCompletion(
            turn_id="2026-10-06/1000",
            inputs=(ContextTurnInput("question", 1.0),),
            working={},
            background_refs=("home:top/agent/AGENT", "home:top/agent/AGENT"),
            trace=SealedTurnTrace(turn_id="2026-10-06/1000", entries=()),
        )


async def test_control_scope_tracks_background_state() -> None:
    engine = _engine()
    with pytest.raises(ContextContractError):
        engine.control_scope()

    turn_id = engine.begin_turn("hi", turn_id="2026-10-06/422")
    await engine.open_segments(date(2026, 7, 14))
    scope = _scope(turn_id)
    names = [tool.name for tool in engine.control_scope().tools]
    # WHAT is loadable; the Agent core is loaded (and evictable).
    assert CONTROL_LOAD_BACKGROUND in names

    bus = SignalBus()
    normalization = engine.normalize_controls(
        (
            ToolCallRecord(
                id="c1",
                name=CONTROL_LOAD_BACKGROUND,
                arguments={"refs": ["home:top/skills/x"]},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=scope,
    )
    for signal in normalization.signals:
        bus.emit(signal)
    results = await engine.consume_signals(bus)
    assert results == ()
    assert "home:top/skills/x" in engine.background_refs()


async def test_consume_signals_commits_feasible_valid_changes() -> None:
    observations = RecordingObservations()
    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_observations(observations)
        .with_segment(_registration(TextSource()))
        .build()
    )
    turn_id = engine.begin_turn("hi", turn_id="2026-10-06/456")
    await engine.open_segments(date(2026, 7, 14))
    scope = _scope(turn_id)
    bus = SignalBus()

    normalization = engine.normalize_controls(
        (
            ToolCallRecord(
                id="ok",
                name=CONTROL_SET_MILESTONE,
                arguments={"key": "m", "content": "made progress"},
                kind=ToolKind.CONTROL,
            ),
            ToolCallRecord(
                id="bad",
                name=CONTROL_REMOVE_TODO,
                arguments={"key": "missing"},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=scope,
    )
    assert len(normalization.signals) == 2
    for signal in normalization.signals:
        bus.emit(signal)

    results = await engine.consume_signals(bus)
    assert len(results) == 1
    assert results[0].call_id == "bad"
    assert "Unknown todo key" in results[0].model_feedback
    assert engine.working_snapshot()["milestones"] == [
        {"key": "m", "content": "made progress"}
    ]
    applied = [
        event
        for event in observations.events
        if event.name == "context.control.applied"
    ]
    assert len(applied) == 1
    assert applied[0].scope == scope
    assert applied[0].payload == {
        "call_id": "ok",
        "operation": "set_milestone",
        "details": {"key": "m", "content": "made progress"},
    }


async def test_applied_controls_follow_installed_order_and_do_not_publish_owner_refreshes() -> (
    None
):
    observations = RecordingObservations()
    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_observations(observations)
        .with_segment(_registration(TextSource()))
        .build()
    )
    scope = _scope(engine.begin_turn("hi", turn_id="2026-10-06/513"))
    await engine.open_segments(date(2026, 7, 14))
    controls = (
        ("load_background", {"refs": ["home:top/skills/x"]}),
        ("set_todo", {"key": "t", "content": "verify", "status": "pending"}),
        ("set_milestone", {"key": "m", "content": "Found the cause"}),
        ("set_todo", {"key": "t", "content": "verified", "status": "done"}),
        ("remove_todo", {"key": "t"}),
        ("remove_milestone", {"key": "m"}),
        ("evict_background", {"refs": ["home:top/skills/x"]}),
    )
    bus = SignalBus()
    for index, (name, arguments) in enumerate(controls):
        normalized = engine.normalize_controls(
            (
                ToolCallRecord(
                    str(index), name, to_json_object(arguments), ToolKind.CONTROL
                ),
            ),
            scope=scope,
        )
        for signal in normalized.signals:
            bus.emit(signal)
    assert await engine.consume_signals(bus) == ()
    applied = [
        event
        for event in observations.events
        if event.name == "context.control.applied"
    ]
    assert [event.payload["operation"] for event in applied] == [
        name for name, _ in controls
    ]
    assert all(event.scope == scope for event in applied)
    assert applied[3].payload["details"] == {
        "key": "t",
        "content": "verified",
        "status": "done",
    }
    assert "home:top/skills/x" not in engine.background_refs()
    assert engine.working_snapshot() == {"todos": [], "milestones": []}
    bus.emit(
        build_working_patch_signal(
            WorkingPatch(set_milestones=(Milestone("owner", "refreshed"),)),
            scope=scope,
            source="owner",
            call_id="owner_refresh",
        )
    )
    assert await engine.consume_signals(bus) == ()
    assert len(
        [
            event
            for event in observations.events
            if event.name == "context.control.applied"
        ]
    ) == len(controls)


async def test_consume_signals_validates_working_batch_against_projection() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi", turn_id="2026-10-06/573"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()

    setup = engine.normalize_controls(
        (
            ToolCallRecord(
                id="set",
                name=CONTROL_SET_TODO,
                arguments={"key": "t1", "content": "write", "status": "pending"},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=scope,
    )
    for signal in setup.signals:
        bus.emit(signal)
    assert await engine.consume_signals(bus) == ()

    batch = engine.normalize_controls(
        (
            ToolCallRecord(
                id="remove_1",
                name=CONTROL_REMOVE_TODO,
                arguments={"key": "t1"},
                kind=ToolKind.CONTROL,
            ),
            ToolCallRecord(
                id="remove_2",
                name=CONTROL_REMOVE_TODO,
                arguments={"key": "t1"},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=scope,
    )
    for signal in batch.signals:
        bus.emit(signal)

    results = await engine.consume_signals(bus)
    assert len(results) == 1
    assert results[0].call_id == "remove_2"
    assert "Unknown todo key" in results[0].model_feedback
    assert engine.working_snapshot()["todos"] == []


async def test_consume_signal_results_preserve_signal_order() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi", turn_id="2026-10-06/621"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
            payload={
                "call_id": "background_first",
                "load_refs": ["missing"],
                "evict_refs": [],
            },
        )
    )
    bus.emit(
        build_working_patch_signal(
            WorkingPatch(remove_todos=("missing",)),
            call_id="working_second",
            scope=scope,
            source="test",
        )
    )

    results = await engine.consume_signals(bus)

    assert [result.sequence for result in results] == [1, 2]
    assert results[0].call_id == "background_first"
    assert results[1].call_id == "working_second"


async def test_consume_signals_validates_background_batch_against_projection() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi", turn_id="2026-10-06/654"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
            payload={
                "call_id": "load",
                "load_refs": ["home:top/skills/x"],
                "evict_refs": [],
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
                "load_refs": [],
                "evict_refs": ["home:top/skills/x"],
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
                "load_refs": [],
                "evict_refs": ["home:top/skills/x"],
            },
        )
    )

    results = await engine.consume_signals(bus)
    assert len(results) == 1
    assert results[0].call_id == "evict_again"
    assert "not loaded" in results[0].model_feedback
    assert "home:top/skills/x" not in engine.background_refs()


async def test_background_signal_rejects_load_evict_conflict() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi", turn_id="2026-10-06/703"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
            payload={
                "call_id": "conflict",
                "load_refs": ["home:top/skills/x"],
                "evict_refs": ["home:top/skills/x"],
            },
        )
    )

    results = await engine.consume_signals(bus)
    assert len(results) == 1
    assert results[0].call_id == "conflict"
    assert "cannot load and evict" in results[0].model_feedback
    assert "home:top/skills/x" not in engine.background_refs()


async def test_background_signal_treats_loaded_link_load_as_noop() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi", turn_id="2026-10-06/728"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
            payload={
                "call_id": "reload_default",
                "load_refs": ["home:top/agent/AGENT"],
                "evict_refs": [],
            },
        )
    )

    results = await engine.consume_signals(bus)

    assert results == ()
    assert engine.background_refs() == ("home:top/agent/AGENT",)


async def test_home_background_is_rebuilt_for_each_user_turn() -> None:
    engine = _engine()
    first_turn = engine.begin_turn("first", turn_id="2026-10-06/752")
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=_scope(first_turn),
            payload={
                "call_id": "load_x",
                "load_refs": ["home:top/skills/x"],
                "evict_refs": [],
            },
        )
    )

    assert await engine.consume_signals(bus) == ()
    assert engine.background_refs() == (
        "home:top/agent/AGENT",
        "home:top/skills/x",
    )
    engine.end_turn()
    await engine.close_segments()

    engine.begin_turn("second", turn_id="2026-10-06/776")
    assert engine.background_refs() == ()
    await engine.open_segments(date(2026, 7, 14))
    assert engine.background_refs() == ("home:top/agent/AGENT",)


async def test_context_observes_committed_background_selection() -> None:
    observations = RecordingObservations()
    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_observations(observations)
        .with_segment(
            _registration(
                TextSource(
                    {
                        "home:top/agent/AGENT": "core rules",
                        "home:top/skills/x": "concept body",
                    }
                )
            )
        )
        .build()
    )
    scope = _scope(engine.begin_turn("hi", turn_id="2026-10-06/796"))
    await engine.open_segments(date(2026, 7, 19))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
            payload={
                "call_id": "load_x",
                "load_refs": ["home:top/skills/x"],
                "evict_refs": [],
            },
        )
    )

    assert await engine.consume_signals(bus) == ()

    background_events = [
        event
        for event in observations.events
        if event.name.startswith("context.background.")
    ]
    assert [event.name for event in background_events] == [
        "context.background.snapshot",
        "context.background.changed",
    ]
    assert background_events[-1].payload["loaded_refs"] == ["home:top/skills/x"]
    assert "concept body" in str(engine.compose(_prompt()).messages)


async def test_trace_append_rejects_unknown_kind() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi", turn_id="2026-10-06/829"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_TRACE_APPEND,
            source="test",
            scope=scope,
            payload={"kind": "unknown_trace_kind"},
        )
    )

    with pytest.raises(ContextContractError, match="Unknown trace append kind"):
        await engine.consume_signals(bus)
    assert engine.trace_kinds() == (TraceKind.INPUT,)


async def test_consume_trace_and_input_signals() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi", turn_id="2026-10-06/848"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()

    bus.emit(
        build_trace_decision_signal(
            AssistantMessage.from_parts(
                TextPart("choose tools"),
                JsonPart({"hint": "scan first"}),
                reasoning=Reasoning(content="private trace", summary="scan plan"),
                tool_calls=(
                    ToolCallRecord(id="a1", name="workspace.list", arguments={}),
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
                tool_name="workspace.list",
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
    bus.emit(
        build_input_append_signal("also do this", scope=scope, source="agent.inputs")
    )
    # Non-context signals stay queued for other consumers.
    bus.emit(Signal(name="loop.control.request", source="agent.inputs", scope=scope))

    results = await engine.consume_signals(bus)
    assert results == ()
    assert engine.trace_kinds() == (
        TraceKind.INPUT,
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
        TraceKind.PHASE_NOTE,
    )
    assert len(bus) == 1
    stack = engine.compose(_prompt("next"))
    decision = next(
        message for message in stack.messages if message.label == "decision"
    )
    assert isinstance(decision, AssistantMessage)
    assert isinstance(decision.parts[1], JsonPart)
    assert decision.reasoning is not None
    assert decision.reasoning.summary == "scan plan"

    merged = engine.merge_pending_inputs()
    assert merged == 1
    stack = engine.compose(_prompt("next"))
    assert [message.label for message in stack.messages].count("user_input") == 2
    assert engine.trace_kinds() == (
        TraceKind.INPUT,
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
        TraceKind.PHASE_NOTE,
        TraceKind.INPUT,
    )
    assert engine.merge_pending_inputs() == 0


async def test_compress_via_engine() -> None:
    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_trace_heap(
            chunk_max_chars=12000,
            branch_factor=4,
            min_hot_entries=0,
        )
        .build()
    )
    turn_id = engine.begin_turn("hi", turn_id="2026-10-06/938")
    await engine.open_segments(date(2026, 7, 14))
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
    await engine.consume_signals(bus)

    report = engine.compress()
    assert report.changed is True
    assert report.compacted_count == 4
    assert engine.trace_kinds() == (TraceKind.INPUT,) + (TraceKind.PHASE_NOTE,) * 3
    nodes = ((await engine.inspect(f"turn:trace/{turn_id}")).to_json())["items"]
    assert isinstance(nodes, list) and nodes
    root = nodes[0]
    assert isinstance(root, dict)
    ref = root["ref"]
    assert isinstance(ref, str)
    page = (await engine.inspect(ref)).to_json()
    assert page["kind"] == "context_trace"
    assert page["ref"] == ref
    interactions = page["items"]
    assert isinstance(interactions, list)
    assert len(interactions) == 4
    for item in interactions:
        assert isinstance(item, dict)
        assert item["kind"] == "child"
        detail = (await engine.inspect(str(item["ref"]))).to_json()
        assert "phase_note" in str(detail) or "User input" in str(detail)
    assert "source" not in page
    assert "cursor" not in page


async def test_question_and_choice_reply_are_readable_trace_facts() -> None:
    from tests.action_helpers import builtin_catalog
    from tinysoul.infra.time import CalendarDay
    from tinysoul.kernel.action import ActionCall, ActionExecution, ActionFramework
    from tinysoul.kernel.action.builtins.core.actions import CoreAskActionExecutor
    from tinysoul.kernel.action.execution.executor import ActionExecutionContext
    from tinysoul.kernel.action.planning.rendering import ActionResultRenderer
    from tinysoul.kernel.interaction import AnswerKind, QuestionAnswer
    from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
    from tinysoul.plugins.session.completion import project_turn_record

    context = _engine()
    turn_id = context.begin_turn("review the document", turn_id="2026-07-14/990")
    await context.open_segments(date(2026, 7, 14))
    scope = _scope(turn_id)
    call = ActionCall(
        "ask",
        "core.ask",
        {
            "question": "Keep the document?",
            "details": "The full text preserves the audit evidence.",
            "options": [
                {
                    "id": "a",
                    "label": "Keep the full text",
                    "description": "Retain examples",
                }
            ],
        },
        1,
    )
    context.register_action_calls((call,), cycle_id="c")
    result = await CoreAskActionExecutor().execute(
        ActionExecution(
            builtin_catalog().get_action("core.ask"),
            call,
            ActionFramework("ask", "batch", scope, "core"),
        ),
        ActionExecutionContext(),
    )
    context.record_action_result(result, cycle_id="c")
    rendered = ActionResultRenderer().render_tool_result(result)
    assert rendered.canonical_message == rendered.visible_message
    assert "Keep the full text" in str(rendered.visible_message)
    assert "Retain examples" in str(rendered.visible_message)
    bus = SignalBus()
    bus.emit(
        build_trace_action_result_signal(
            rendered.visible_message, scope=scope, source="test", cycle_id="c"
        )
    )
    bus.emit(
        build_input_append_signal(
            "a",
            scope=scope,
            source="test",
            reply_to=result.result_id,
            answer=QuestionAnswer(
                AnswerKind.CHOICE, option_id="a", comment="Add citations"
            ),
        )
    )
    await context.consume_signals(bus)
    assert context.trace_kinds() == (TraceKind.INPUT, TraceKind.ACTION_RESULT)
    context.merge_pending_inputs()
    assert context.merge_pending_inputs() == 0
    trace_messages = [
        message
        for message in context.compose(_prompt()).messages
        if message.label in {"trace_input", "action_result"}
    ]
    assert len(trace_messages) == 3
    reply = str(trace_messages[-1])
    assert all(
        text in reply
        for text in (
            "The full text preserves the audit evidence.",
            "Keep the document?",
            "Keep the full text",
            "Retain examples",
            "Add citations",
        )
    )
    root = f"turn:trace/{turn_id}"
    direct = await context.inspect(f"{root}#input/1")
    assert "The full text preserves the audit evidence." in direct.model_text
    assert "Add citations" in direct.model_text
    assert direct.items[0].unit.data["text"] == "a"
    hits = ((await context.inspect(root, query="Add citations")).to_json())["items"]
    assert isinstance(hits, list) and hits
    completed = context.end_turn()
    record = project_turn_record(
        completed,
        day=CalendarDay.parse("2026-07-14"),
        output=None,
        exhausted=False,
        status=TurnOutcomeStatus.AWAITING_USER,
    )
    assert len(record.inputs) == 2 and len(record.actions) == 1 and not record.notes
    from tinysoul.plugins.session.views.navigation import project_occurrence

    historical = project_occurrence(record, "input/1")
    assert historical["narrative"] == direct.items[0].unit.text
    assert record.inputs[1].text == "a"
    await context.close_segments()


async def test_abort_turn_discards_active_state() -> None:
    engine = _engine()
    engine.begin_turn("hi", turn_id="2026-10-06/1076")
    await engine.open_segments(date(2026, 7, 14))
    assert engine.turn_active is True
    assert engine.background_refs() == ("home:top/agent/AGENT",)

    engine.abort_turn()
    await engine.close_segments()

    assert engine.turn_active is False
    assert engine.background_refs() == ()
    with pytest.raises(ContextContractError):
        engine.working_snapshot()
    engine.begin_turn("new turn", turn_id="2026-10-06/1088")
    assert engine.turn_active is True


async def test_provider_catalog_metadata_is_automatic_background() -> None:
    class _Provider:
        async def catalog(self, active_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home",
                loadable_refs=("home:top/skills/review",),
                items=(
                    BackgroundCatalogItem(
                        ref="home:top/skills/review",
                        title="Review Home",
                        description="Review pending Home changes.",
                    ),
                ),
            )

        async def load(self, ref: str, active_day: date) -> str:
            return "skill body"

    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_segment(_registration(_Provider()))
        .build()
    )
    engine.begin_turn("review changes", turn_id="2026-10-06/1115")
    await engine.open_segments(date(2026, 7, 14))

    stack = engine.compose(_prompt())

    message = next(
        item for item in stack.messages if item.label == "background:catalog:home"
    )
    assert isinstance(message.parts[0], TextPart)
    assert all(
        value in message.parts[0].text
        for value in (
            "home:top/skills/review",
            "Review Home",
            "Review pending Home changes.",
        )
    )
    assert engine.background_refs() == ()


async def test_heap_refresh_replaces_loaded_content_and_catalog_atomically() -> None:
    source = TextSource()
    engine = (
        ContextEngineBuilder(system_text="identity")
        .with_segment(_registration(source))
        .build()
    )
    turn = engine.begin_turn("update", turn_id="2026-10-06/1144")
    await engine.open_segments(date(2026, 7, 14))
    source.texts["home:top/agent/AGENT"] = "new rules"
    source.texts["home:top/skills/new"] = "new skill"
    bus = SignalBus()
    bus.emit(
        Signal(
            name="context.home.update",
            source="home.action",
            scope=_scope(turn),
            payload={"refresh": True},
        )
    )
    assert "new rules" not in str(engine.compose(_prompt()).messages)
    await engine.consume_signals(bus)
    assert "new rules" in str(engine.compose(_prompt()).messages)
    assert "new skill" not in str(engine.compose(_prompt()).messages)
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=_scope(turn),
            payload={"call_id": "load_new", "load_refs": ["home:top/skills/new"]},
        )
    )
    assert await engine.consume_signals(bus) == ()
    assert "new skill" in str(engine.compose(_prompt()).messages)
    await engine.close_segments()


def test_engine_exposes_snapshots_not_mutable_context_holders() -> None:
    engine = _engine()
    engine.begin_turn("hi", turn_id="2026-10-06/1176")

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
        (
            ContextEngineBuilder(system_text="sys")
            .with_compression_trigger_ratio(0.5)
            .with_compression_target_ratio(0.5)
            .build()
        )
