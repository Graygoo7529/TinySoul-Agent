"""Tests for the context engine facade."""

from __future__ import annotations


import asyncio
from dataclasses import dataclass, field
from datetime import date
from threading import Event
from typing import cast

import pytest

from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.kernel.context import (
    BackgroundCatalog,
    BackgroundCatalogItem,
    CONTROL_LOAD_BACKGROUND,
    CONTROL_REMOVE_TODO,
    CONTROL_SET_MILESTONE,
    CONTROL_SET_TODO,
    SIGNAL_BACKGROUND_PATCH,
    SIGNAL_TRACE_APPEND,
    ContextContractError,
    ContextInvariantError,
    ContextEngineBuilder,
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
from tinysoul.kernel.context.providers import BackgroundEntryProvider
from tinysoul.kernel.context.segments import (
    SegmentCapability,
    SegmentDescriptor,
    SegmentShape,
    SegmentSlot,
)
from tinysoul.kernel.context.builtin.trace import SealedTurnTrace, TraceKind
from tinysoul.kernel.context.signals import build_working_patch_signal
from tinysoul.kernel.context.builtin.working import WorkingPatch
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
            "home:agent@AGENT": "core rules",
            "home:skills@x": "entity x",
        }
    )

    async def catalog(self, business_day: date) -> BackgroundCatalog:
        return BackgroundCatalog(
            owner="home",
            default_links=("home:agent@AGENT",),
            loadable_links=tuple(self.texts),
            evictable_default_links=("home:agent@AGENT",),
        )

    async def load(self, link: str, business_day: date) -> str:
        return self.texts[link]


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
        async def catalog(self, business_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home",
                loadable_links=("home:agent@AGENT",),
                default_links=("home:agent@AGENT",),
                items=(
                    BackgroundCatalogItem(
                        link="home:agent@AGENT", title="Rules", description="Rules"
                    ),
                ),
            )

        async def load(self, link: str, business_day: date) -> str:
            return ""  # A broken owner response after the catalog was prepared.

    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_segment(_registration(Provider()))
        .build()
    )
    engine.begin_turn("question")
    with pytest.raises(ContextInvariantError, match="content must be non-empty"):
        await engine.open_segments(date(2026, 9, 15))
    with pytest.raises(ContextContractError, match="opened"):
        engine.compose(_prompt())
    assert engine.background_links() == ()


async def test_cancelled_background_prepare_joins_read_without_installing_view() -> (
    None
):
    entered = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()

    class Provider:
        async def catalog(self, business_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home",
                loadable_links=("home:agent@AGENT",),
                default_links=("home:agent@AGENT",),
            )

        async def load(self, link: str, business_day: date) -> str:
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
    engine.begin_turn("question")
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

        async def catalog(self, business_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home", loadable_links=("home:skills@guide",)
            )

        async def load(self, link: str, business_day: date) -> str:
            self.calls += 1
            if self.calls == 1:
                loop.call_soon_threadsafe(entered.set)
                operations = JoinedOperations()
                assert await operations.run(lambda: release.wait(timeout=5))
                operations.check_cancelled()
                raise ContextInvariantError("Background temporarily unavailable")
            return "Loaded details"

    loader = Loader()
    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_segment(_registration(loader))
        .build()
    )
    turn_id = engine.begin_turn("question")
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
                arguments={"links": ["home:skills@guide"]},
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
    assert await engine.consume_signal_batch(batch) == ()
    assert engine.working_snapshot()["milestones"]
    assert engine.background_links() == ("home:skills@guide",)
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

    turn_id = engine.begin_turn("please help")
    await engine.open_segments(date(2026, 7, 14))
    assert turn_id
    with pytest.raises(ContextContractError):
        engine.begin_turn("again")
    await engine.open_segments(date(2026, 7, 14))

    stack = engine.compose(_prompt("Phase one."))
    labels = [message.label for message in stack.messages]
    assert labels[0] == "identity"
    assert labels[1] == "user_input"
    assert labels[2] == "background:journal"

    summary = engine.end_turn()
    assert summary.turn_id == turn_id
    assert summary.inputs[0].text == "please help"
    assert summary.background_links == ("home:agent@AGENT",)
    assert not engine.turn_active


async def test_foldable_action_result_persists_only_compact_trace_payload() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("read workspace"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        build_trace_action_result_signal(
            ToolResultMessage.from_json(
                call_id="read_1",
                tool_name="workspace.read",
                value={"link": "workspace:a.md", "text": "sensitive body"},
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
                    "payload": {"link": "workspace:a.md", "folded": True},
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
    trace_message = summary.trace.entries[0].message
    assert isinstance(trace_message, ToolResultMessage)
    content = trace_message.parts
    assert isinstance(content[0], JsonPart)
    assert content[0].value["payload"] == {
        "link": "workspace:a.md",
        "folded": True,
    }
    assert summary.trace.entries[0].origin_refs == ("workspace:a.md",)


def test_context_batch_and_turn_summary_validate_protocol_fields() -> None:
    with pytest.raises(ContextContractError, match="turn_id"):
        ContextSignalBatch(turn_id="")
    with pytest.raises(ContextContractError, match="Signal"):
        ContextSignalBatch(
            turn_id="turn_1",
            signals=cast(tuple[Signal, ...], (object(),)),
        )
    with pytest.raises(ContextContractError, match="background_links"):
        ContextTurnCompletion(
            turn_id="turn_1",
            inputs=(ContextTurnInput("question", 1.0),),
            working={},
            background_links=("home:agent@AGENT", "home:agent@AGENT"),
            trace=SealedTurnTrace(turn_id="turn_1", entries=()),
        )


async def test_control_scope_tracks_background_state() -> None:
    engine = _engine()
    with pytest.raises(ContextContractError):
        engine.control_scope()

    turn_id = engine.begin_turn("hi")
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
                arguments={"links": ["home:skills@x"]},
                kind=ToolKind.CONTROL,
            ),
        ),
        scope=scope,
    )
    for signal in normalization.signals:
        bus.emit(signal)
    results = await engine.consume_signals(bus)
    assert results == ()
    assert "home:skills@x" in engine.background_links()


async def test_consume_signals_commits_feasible_valid_changes() -> None:
    engine = _engine()
    turn_id = engine.begin_turn("hi")
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
    assert engine.working_snapshot()["milestones"][0]["key"] == "m"


async def test_consume_signals_validates_working_batch_against_projection() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi"))
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
    scope = _scope(engine.begin_turn("hi"))
    await engine.open_segments(date(2026, 7, 14))
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
    scope = _scope(engine.begin_turn("hi"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
            payload={
                "call_id": "load",
                "load_links": ["home:skills@x"],
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
                "evict_links": ["home:skills@x"],
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
                "evict_links": ["home:skills@x"],
            },
        )
    )

    results = await engine.consume_signals(bus)
    assert len(results) == 1
    assert results[0].call_id == "evict_again"
    assert "not loaded" in results[0].model_feedback
    assert "home:skills@x" not in engine.background_links()


async def test_background_signal_rejects_load_evict_conflict() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
            payload={
                "call_id": "conflict",
                "load_links": ["home:skills@x"],
                "evict_links": ["home:skills@x"],
            },
        )
    )

    results = await engine.consume_signals(bus)
    assert len(results) == 1
    assert results[0].call_id == "conflict"
    assert "cannot load and evict" in results[0].model_feedback
    assert "home:skills@x" not in engine.background_links()


async def test_background_signal_treats_loaded_link_load_as_noop() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi"))
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
            payload={
                "call_id": "reload_default",
                "load_links": ["home:agent@AGENT"],
                "evict_links": [],
            },
        )
    )

    results = await engine.consume_signals(bus)

    assert results == ()
    assert engine.background_links() == ("home:agent@AGENT",)


async def test_home_background_is_rebuilt_for_each_user_turn() -> None:
    engine = _engine()
    first_turn = engine.begin_turn("first")
    await engine.open_segments(date(2026, 7, 14))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=_scope(first_turn),
            payload={
                "call_id": "load_x",
                "load_links": ["home:skills@x"],
                "evict_links": [],
            },
        )
    )

    assert await engine.consume_signals(bus) == ()
    assert engine.background_links() == (
        "home:agent@AGENT",
        "home:skills@x",
    )
    engine.end_turn()
    await engine.close_segments()

    engine.begin_turn("second")
    assert engine.background_links() == ()
    await engine.open_segments(date(2026, 7, 14))
    assert engine.background_links() == ("home:agent@AGENT",)


async def test_context_observes_committed_background_selection() -> None:
    observations = RecordingObservations()
    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_observations(observations)
        .with_segment(
            _registration(
                TextSource(
                    {"home:agent@AGENT": "core rules", "home:skills@x": "concept body"}
                )
            )
        )
        .build()
    )
    scope = _scope(engine.begin_turn("hi"))
    await engine.open_segments(date(2026, 7, 19))
    bus = SignalBus()
    bus.emit(
        Signal(
            name=SIGNAL_BACKGROUND_PATCH,
            source="test",
            scope=scope,
            payload={
                "call_id": "load_x",
                "load_links": ["home:skills@x"],
                "evict_links": [],
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
    assert background_events[-1].payload["loaded_links"] == ["home:skills@x"]
    assert "concept body" in str(engine.compose(_prompt()).messages)


async def test_trace_append_rejects_unknown_kind() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi"))
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
    assert engine.trace_kinds() == ()


async def test_consume_trace_and_input_signals() -> None:
    engine = _engine()
    scope = _scope(engine.begin_turn("hi"))
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
        TraceKind.DECISION,
        TraceKind.ACTION_RESULT,
        TraceKind.PHASE_NOTE,
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
    turn_id = engine.begin_turn("hi")
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
    assert report.compacted_count == 3
    assert engine.trace_kinds() == (TraceKind.PHASE_NOTE,) * 3
    nodes = (await engine.inspect(f"turn:trace@{turn_id}"))["nodes"]
    assert isinstance(nodes, list) and nodes
    root = nodes[0]
    assert isinstance(root, dict)
    ref = root["ref"]
    assert isinstance(ref, str)
    page = await engine.inspect(ref)
    assert page["kind"] == "context_trace_leaf"
    assert page["ref"] == ref
    interactions = page["interactions"]
    assert isinstance(interactions, list)
    assert len(interactions) == 3
    for item in interactions:
        assert isinstance(item, dict)
        assert item["kind"] == "phase_note"
    assert "source" not in page
    assert "cursor" not in page


async def test_abort_turn_discards_active_state() -> None:
    engine = _engine()
    engine.begin_turn("hi")
    await engine.open_segments(date(2026, 7, 14))
    assert engine.turn_active is True
    assert engine.background_links() == ("home:agent@AGENT",)

    engine.abort_turn()
    await engine.close_segments()

    assert engine.turn_active is False
    assert engine.background_links() == ()
    with pytest.raises(ContextContractError):
        engine.working_snapshot()
    engine.begin_turn("new turn")
    assert engine.turn_active is True


async def test_provider_catalog_metadata_is_automatic_background() -> None:
    class _Provider:
        async def catalog(self, business_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home",
                loadable_links=("home:skills@review",),
                items=(
                    BackgroundCatalogItem(
                        link="home:skills@review",
                        title="Review Home",
                        description="Review pending Home changes.",
                    ),
                ),
            )

        async def load(self, link: str, business_day: date) -> str:
            return "skill body"

    engine = (
        ContextEngineBuilder(system_text="sys")
        .with_segment(_registration(_Provider()))
        .build()
    )
    engine.begin_turn("review changes")
    await engine.open_segments(date(2026, 7, 14))

    stack = engine.compose(_prompt())

    message = next(
        item for item in stack.messages if item.label == "background:catalog:home"
    )
    assert isinstance(message.parts[0], JsonPart)
    assert message.parts[0].value == {
        "owner": "home",
        "items": [
            {
                "link": "home:skills@review",
                "title": "Review Home",
                "description": "Review pending Home changes.",
            }
        ],
    }
    assert engine.background_links() == ()


async def test_heap_refresh_replaces_loaded_content_and_catalog_atomically() -> None:
    source = TextSource()
    engine = (
        ContextEngineBuilder(system_text="identity")
        .with_segment(_registration(source))
        .build()
    )
    turn = engine.begin_turn("update")
    await engine.open_segments(date(2026, 7, 14))
    source.texts["home:agent@AGENT"] = "new rules"
    source.texts["home:skills@new"] = "new skill"
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
            payload={"call_id": "load_new", "load_links": ["home:skills@new"]},
        )
    )
    assert await engine.consume_signals(bus) == ()
    assert "new skill" in str(engine.compose(_prompt()).messages)
    await engine.close_segments()


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
        (
            ContextEngineBuilder(system_text="sys")
            .with_compression_trigger_ratio(0.5)
            .with_compression_target_ratio(0.5)
            .build()
        )
