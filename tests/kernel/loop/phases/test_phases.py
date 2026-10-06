from __future__ import annotations


from tests.action_helpers import builtin_catalog

from datetime import date as CalendarDate

from tinysoul.kernel.context.background import heap_segment_registration
from tinysoul.kernel.context.segments import (
    SegmentCapability,
    SegmentDescriptor,
    SegmentShape,
    SegmentSlot,
)

from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.workspace.projection import (
    workspace_refresh_signal,
)

from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from tinysoul.kernel.action import (
    ActionEngine,
    ActionNormalization,
)
from tests.support.model_uses import action_tasks
from tinysoul.plugins.execution.actions import EXECUTION_ACTIONS
from tinysoul.kernel.context import (
    BackgroundCatalog,
    BackgroundCatalogItem,
    ContextEngine,
    ContextEngineBuilder,
    ControlResult,
    ControlResultStage,
)
from tinysoul.kernel.context.builtin.trace import TraceKind
from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.messages import JsonPart, MessageStack, TextPart
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import (
    JsonAnswer,
    RawResponse,
    TaskFailure,
    TaskResult,
)
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind, ToolUse
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
from tinysoul.plugins.memory.services import MemoryService
from tinysoul.plugins.memory import (
    DailyMemoryDocument,
    MemoryEngine,
    MemorySettings,
    register_memory_actions,
)
from tinysoul.runtime import (
    RUNTIME_TURN_END,
    CyclePhase,
    RunLevel,
    RunScope,
    RuntimeException,
    SignalBus,
    ObservationEvent,
    ObservationLevel,
    RuntimeTrap,
    TrapHandlerRegistry,
)
from tinysoul.plugins.memory.runtime_bridge import RuntimeMemoryBridge
from tinysoul.plugins.workspace import (
    WorkspaceEngine,
    WorkspaceEngineBuilder,
    WorkspaceSettings,
    register_workspace_actions,
)
from tests.action_helpers import FunctionActionEngineBuilder


class FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    async def invoke(self, call: TaskCall) -> TaskResult:
        return await self.run(call)

    async def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self.results.popleft()


@pytest.mark.parametrize("response", ["capacity", "not_sent", "responded"])
async def test_only_a_responded_request_releases_inspect_overlay(response: str) -> None:
    from tinysoul.kernel.context import build_trace_action_result_signal
    from tinysoul.llm.protocol.messages import ToolResultMessage
    from tinysoul.llm.failures import LLM_CONTEXT_CAPACITY_EXCEEDED
    from tinysoul.llm.protocol.responses import TaskResultStatus

    class CapacityLLM:
        async def invoke(self, call: TaskCall) -> TaskResult:
            return await self.run(call)

        async def run(self, call: TaskCall) -> TaskResult:
            if response == "capacity":
                raise RuntimeException(LLM_CONTEXT_CAPACITY_EXCEEDED, "capacity")
            return TaskResult(
                status=TaskResultStatus.FAILURE,
                answer=None,
                raw_response=RawResponse(
                    answer_text="", model_id="fake", provider_id="fake"
                )
                if response == "responded"
                else None,
                failure=TaskFailure(model_feedback="No usable action intent"),
            )

    context = ContextEngineBuilder(system_text="test").build()
    turn_id = context.begin_turn("inspect", turn_id="2026-10-06/120")
    await context.open_segments(CalendarDate(2026, 9, 20))
    scope = RunScope().push(RunLevel.TURN, turn_id)
    full = ToolResultMessage.from_json(
        call_id="inspect",
        tool_name="core.context.inspect",
        value={"detail": "evidence"},
    )
    folded = ToolResultMessage.from_json(
        call_id="inspect",
        tool_name="core.context.inspect",
        value={"ref": "session:map"},
    )
    bus = SignalBus()
    bus.emit(
        build_trace_action_result_signal(
            full,
            canonical_message=folded,
            origin_refs=("session:map",),
            scope=scope,
            source="test",
        )
    )
    await context.consume_signals(bus)
    phase = Phase1Unit(
        context=context,
        action=_action_engine(),
        llm=CapacityLLM(),
        bus=bus,
        task_profile="phase1",
    )
    if response == "capacity":
        with pytest.raises(RuntimeException) as failure:
            await phase.run(scope=scope, cycle_id="cycle_1")
        assert failure.value.reason == LLM_CONTEXT_CAPACITY_EXCEEDED
    else:
        await phase.run(scope=scope, cycle_id="cycle_1")
    assert context.compress(required_chars=100000).folded_overlay_count == (
        1 if response == "responded" else 0
    )
    await context.close_segments()


@dataclass
class RecordingObservations:
    events: list[ObservationEvent] = field(default_factory=list)

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)


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


async def test_phase_units_use_independent_task_profiles() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now", turn_id="2026-10-06/265")
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
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
    )

    phase1 = await Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        task_profile="cycle_planner",
    ).run(
        scope=scope.push(RunLevel.PHASE, CyclePhase.PHASE1.value),
        cycle_id="cycle_1",
    )
    (
        await Phase2Unit(
            context=context,
            action=action,
            llm=llm,
            bus=bus,
            task_profile="cycle_executor",
        ).run(
            selected_domains=phase1.selected_domains,
            scope=scope.push(RunLevel.PHASE, CyclePhase.PHASE2.value),
            cycle_id="cycle_1",
            turn_id=turn_id,
        )
    )

    assert [call.profile for call in llm.calls] == [
        "cycle_planner",
        "cycle_executor",
    ]


async def test_phase1_skill_catalog_and_load_background_feed_phase2_only_for_the_turn() -> (
    None
):
    class _SkillProvider:
        async def catalog(self, active_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home",
                loadable_refs=("home:top/skills/review",),
                items=(
                    BackgroundCatalogItem(
                        ref="home:top/skills/review",
                        title="Review Home",
                        description="Review effective Home changes.",
                    ),
                ),
            )

        async def load(self, ref: str, active_day: date) -> str:
            assert ref == "home:top/skills/review"
            return "SKILL BODY: compare runtime and actual Home."

    context = (
        ContextEngineBuilder(system_text="sys")
        .with_segment(
            heap_segment_registration(
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
                _SkillProvider(),
                signal_name="context.home.update",
            )
        )
        .build()
    )
    turn_id = context.begin_turn("review Home", turn_id="2026-10-06/368")
    await context.open_segments(date(2026, 7, 14))
    action = _action_engine()
    llm = FakeLLM(
        (
            _tool_result(
                ToolCallRecord(
                    id="select_core",
                    name="select_action_domains",
                    arguments={"domains": ["core"]},
                    kind=ToolKind.CONTROL,
                ),
                ToolCallRecord(
                    id="load_review",
                    name="load_background",
                    arguments={"refs": ["home:top/skills/review"]},
                    kind=ToolKind.CONTROL,
                ),
            ),
            _tool_result(
                ToolCallRecord(
                    id="reason",
                    name="core.reason",
                    arguments={
                        "guide_blocks": [{"text": "Review the change."}],
                        "output_blocks": [{"text": "Return JSON."}],
                    },
                    kind=ToolKind.ACTION,
                )
            ),
        )
    )
    bus = SignalBus()
    base_scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
    )

    phase1 = await Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        task_profile="framework",
    ).run(
        scope=base_scope.push(RunLevel.PHASE, CyclePhase.PHASE1.value),
        cycle_id="cycle_1",
    )
    (
        await Phase2Unit(
            context=context,
            action=action,
            llm=llm,
            bus=bus,
            task_profile="framework",
        ).run(
            selected_domains=phase1.selected_domains,
            scope=base_scope.push(RunLevel.PHASE, CyclePhase.PHASE2.value),
            cycle_id="cycle_1",
            turn_id=turn_id,
        )
    )

    phase1_stack = llm.calls[0].messages
    catalog = next(
        message
        for message in phase1_stack.messages
        if message.label == "background:catalog:home"
    )
    assert isinstance(catalog.parts[0], TextPart)
    assert "home:top/skills/review" in catalog.parts[0].text
    assert "Review effective Home changes." in catalog.parts[0].text

    assert "SKILL BODY" not in _message_stack_text(phase1_stack)

    phase2_stack = llm.calls[1].messages
    loaded = next(
        message
        for message in phase2_stack.messages
        if message.label == "background:home:top/skills/review"
    )
    assert isinstance(loaded.parts[0], TextPart)
    assert "SKILL BODY: compare runtime and actual Home." in loaded.parts[0].text

    context.end_turn()
    await context.close_segments()
    await context.close_segments()
    context.begin_turn("next turn", turn_id="2026-10-06/461")
    await context.open_segments(date(2026, 7, 14))
    assert "home:top/skills/review" not in context.background_refs()


async def test_real_memory_actions_record_turn_trace_without_background_mutation(
    tmp_path: Path,
) -> None:
    memory_root = tmp_path / "memory"
    memory = MemoryEngine(
        settings=MemorySettings(root=memory_root),
    )
    memory.write_document(
        DailyMemoryDocument(
            day=date(2026, 7, 13),
            created_on=date(2026, 7, 13),
            updated_on=date(2026, 7, 13),
            content="free-form remembered fact",
        ),
    )
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("recall yesterday", turn_id="2026-10-06/482")
    await context.open_segments(CalendarDate(2026, 7, 12))
    action = _action_engine(memory=memory)
    normalization = action.normalize(
        (
            ToolCallRecord(
                id="recall_1",
                name="memory.inspect",
                arguments={"ref": "memory:daily/2026-07-13"},
                kind=ToolKind.ACTION,
            ),
            ToolCallRecord(
                id="search_1",
                name="memory.search",
                arguments={
                    "source": {
                        "kind": "query",
                        "scope": "all",
                        "query": "remembered",
                    },
                },
                kind=ToolKind.ACTION,
            ),
        )
    )
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )

    outcome = await Phase3Unit(
        context=context,
        action=action,
        bus=SignalBus(),
    ).run(
        normalization=normalization,
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    results = {result.action_name: result for result in outcome.results}
    assert all(result.failure is None for result in results.values()), repr(results)
    disclosed = results["memory.inspect"].payload["items"]
    assert isinstance(disclosed, list)
    markdown = "".join(
        str(item["text"]) for item in disclosed if isinstance(item, dict)
    )
    assert "digest" not in results["memory.inspect"].payload
    assert isinstance(markdown, str)
    assert "free-form remembered fact" in markdown
    items = results["memory.search"].payload["items"]
    assert isinstance(items, list)
    first_item = items[0]
    assert isinstance(first_item, dict)
    assert first_item["ref"] == "memory:daily/2026-07-13"
    assert "period" not in first_item
    assert context.trace_kinds() == (
        TraceKind.INPUT,
        TraceKind.ACTION_RESULT,
        TraceKind.ACTION_RESULT,
    )
    assert context.background_refs() == ()


async def test_real_workspace_inspection_actions_preserve_trace_lifecycle(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "a.md").write_text("alpha needle\n", encoding="utf-8")
    (workspace_root / "b.md").write_text("beta\n", encoding="utf-8")
    workspace = WorkspaceEngineBuilder(WorkspaceSettings(root=workspace_root)).build()
    workspace.reconcile()

    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("inspect workspace", turn_id="2026-10-06/561")
    await context.open_segments(CalendarDate(2026, 7, 12))
    bus = SignalBus()
    llm = FakeLLM(
        (
            _json_result(
                {
                    "answer": "Alpha and beta are present.",
                    "source_ids": ["source_1", "source_2"],
                }
            ),
        )
    )
    action = _action_engine(
        workspace=workspace,
        workspace_context=context,
        workspace_bus=bus,
        workspace_llm=llm,
    )
    normalization = action.normalize(
        (
            ToolCallRecord(
                id="read_1",
                name="workspace.read",
                arguments={
                    "ref": "workspace:a.md",
                    "start_line": 1,
                    "end_line": 1,
                },
                kind=ToolKind.ACTION,
            ),
            ToolCallRecord(
                id="search_1",
                name="workspace.search",
                arguments={
                    "source": {
                        "kind": "query",
                        "scope": {"kind": "workspace"},
                        "query": "needle",
                    },
                },
                kind=ToolKind.ACTION,
            ),
            ToolCallRecord(
                id="analyze_1",
                name="workspace.analyze",
                arguments={
                    "intent": "Compare the selected files.",
                    "references": ["workspace:a.md", "workspace:b.md"],
                },
                kind=ToolKind.ACTION,
            ),
        )
    )
    scope = (
        RunScope()
        .push(RunLevel.AGENT, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )

    outcome = await Phase3Unit(context=context, action=action, bus=bus).run(
        normalization=normalization,
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert [result.status.value for result in outcome.results] == [
        "success",
        "success",
        "success",
    ]
    assert len(llm.calls) == 1
    entries = context.seal_trace().entries
    entries = tuple(entry for entry in entries if entry.kind is TraceKind.ACTION_RESULT)
    assert len(entries) == 3
    for entry in entries[:2]:
        assert entry.visible_overlay is not None
        assert isinstance(entry.visible_overlay.parts[0], JsonPart)
        assert isinstance(entry.message.parts[0], JsonPart)
        assert "alpha needle" in str(entry.visible_overlay.parts[0].value)
        assert "evidence" not in str(entry.message.parts[0].value)
    assert entries[2].visible_overlay is None
    assert isinstance(entries[2].message.parts[0], JsonPart)
    analyze_payload = entries[2].message.parts[0].value["payload"]
    assert isinstance(analyze_payload, dict)
    assert analyze_payload["answer"] == ("Alpha and beta are present.")
    assert context.compress(required_chars=0).folded_overlay_count == 0
    from tinysoul.llm.protocol.messages import MessageStack

    context.mark_model_consumed(
        MessageStack(tuple(entry.visible_message for entry in entries))
    )
    assert context.compress(required_chars=0).folded_overlay_count == 2
    assert all(entry.visible_overlay is None for entry in context.seal_trace().entries)

    summary = context.end_turn()
    assert all(entry.visible_overlay is None for entry in summary.trace.entries)
    assert "Alpha and beta are present." in str(summary.trace)


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
                )
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


async def test_phase1_applies_working_reconciliation_before_returning() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("finish current work", turn_id="2026-10-06/802")
    await context.open_segments(CalendarDate(2026, 7, 12))
    action = _action_engine()
    bus = SignalBus()
    llm = FakeLLM(
        (
            _tool_result(
                ToolCallRecord(
                    id="select_workspace",
                    name="select_action_domains",
                    arguments={"domains": ["workspace"]},
                    kind=ToolKind.CONTROL,
                ),
                ToolCallRecord(
                    id="start_report",
                    name="set_todo",
                    arguments={
                        "key": "report",
                        "content": "Write the report",
                        "status": "in_progress",
                    },
                    kind=ToolKind.CONTROL,
                ),
            ),
            _tool_result(
                ToolCallRecord(
                    id="select_core",
                    name="select_action_domains",
                    arguments={"domains": ["core"]},
                    kind=ToolKind.CONTROL,
                ),
                ToolCallRecord(
                    id="finish_report",
                    name="set_todo",
                    arguments={
                        "key": "report",
                        "content": "Write the report",
                        "status": "done",
                    },
                    kind=ToolKind.CONTROL,
                ),
            ),
        )
    )
    turn_scope = RunScope().push(RunLevel.AGENT, "program").push(RunLevel.TURN, turn_id)
    unit = Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        task_profile="framework",
    )

    outcome_1 = await unit.run(
        scope=turn_scope.push(RunLevel.CYCLE, "cycle_1").push(
            RunLevel.PHASE, CyclePhase.PHASE1.value
        ),
        cycle_id="cycle_1",
    )
    outcome = await unit.run(
        scope=turn_scope.push(RunLevel.CYCLE, "cycle_2").push(
            RunLevel.PHASE, CyclePhase.PHASE1.value
        ),
        cycle_id="cycle_2",
    )

    assert outcome_1.selected_domains == ("workspace",)
    assert outcome.selected_domains == ("core",)
    assert context.working_snapshot()["todos"] == [
        {"key": "report", "content": "Write the report", "status": "done"}
    ]


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
        FunctionActionEngineBuilder(builtin_catalog())
        .mark_actions_unsupported("core.session.organize")
        .register_function("core.answer", lambda execution, context: {"text": "done"})
        .register_function("core.reason", lambda execution, context: {"ok": True})
        .register_function(
            "home.resource.delete", lambda execution, context: {"deleted": True}
        )
        .register_function(
            "home.resource.patch", lambda execution, context: {"patched": True}
        )
        .register_function("home.inspect", lambda execution, context: {"read": True})
        .register_function(
            "home.resource.write", lambda execution, context: {"written": True}
        )
        .register_function(
            "home.top.delete", lambda execution, context: {"deleted": True}
        )
        .register_function(
            "home.top.patch", lambda execution, context: {"patched": True}
        )
        .register_function(
            "home.top.write", lambda execution, context: {"written": True}
        )
        .register_function("home.search", lambda execution, context: {"items": []})
        .register_function("memory.search", lambda execution, context: {"items": []})
        .register_function("memory.memorize", lambda execution, context: {"digest": ""})
        .register_function("memory.inspect", lambda execution, context: {"text": ""})
        .register_function(
            "home.prompt_mount.patch", lambda execution, context: {"patched": True}
        )
        .register_function(
            "home.prompt_mount.write", lambda execution, context: {"written": True}
        )
        .register_function(
            "core.context.inspect",
            lambda execution, context: {},
            executor_id="context.inspect",
        )
        .register_function(
            "workspace.delete", lambda execution, context: {"deleted": True}
        )
        .register_function(
            "workspace.describe", lambda execution, context: {"described": True}
        )
        .register_function(
            "workspace.edit", lambda execution, context: {"patched": True}
        )
        .register_function(
            "workspace.restore", lambda execution, context: {"restored": True}
        )
        .register_function(
            "workspace.trash_list", lambda execution, context: {"items": []}
        )
        .register_function("workspace.list", emit_invalid_sync)
        .register_function(
            "workspace.append", lambda execution, context: {"appended": True}
        )
        .register_function(
            "workspace.compose", lambda execution, context: {"created": True}
        )
        .mark_actions_unsupported(
            "core.wait",
            "core.job.status",
            "core.job.stop",
            "core.job.wait",
            "core.ask",
            *EXECUTION_ACTIONS,
            "workspace.convert_with_markitdown",
            "workspace.convert_with_pypdf",
            "web.discover_pages",
            "web.fetch_with_defuddle",
            "web.fetch_with_trafilatura",
            "web.search_by_kimi",
            "workspace.analyze",
            "workspace.write",
            "workspace.move",
            "workspace.mkdir",
            "workspace.tag",
            "workspace.read",
            "workspace.search",
        )
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


def _action_engine(
    *,
    memory: MemoryEngine | None = None,
    workspace: WorkspaceEngine | None = None,
    workspace_context: ContextEngine | None = None,
    workspace_bus: SignalBus | None = None,
    workspace_llm: FakeLLM | None = None,
) -> ActionEngine:
    builder = (
        FunctionActionEngineBuilder(builtin_catalog())
        .mark_actions_unsupported("core.session.organize")
        .register_function("core.answer", lambda execution, context: {"text": "done"})
        .register_function("core.reason", lambda execution, context: {"ok": True})
        .register_function(
            "home.resource.delete", lambda execution, context: {"deleted": True}
        )
        .register_function(
            "home.resource.patch", lambda execution, context: {"patched": True}
        )
        .register_function("home.inspect", lambda execution, context: {"read": True})
        .register_function(
            "home.resource.write", lambda execution, context: {"written": True}
        )
        .register_function(
            "home.top.delete", lambda execution, context: {"deleted": True}
        )
        .register_function(
            "home.top.patch", lambda execution, context: {"patched": True}
        )
        .register_function(
            "home.top.write", lambda execution, context: {"written": True}
        )
        .register_function("home.search", lambda execution, context: {"items": []})
        .register_function(
            "home.prompt_mount.patch", lambda execution, context: {"patched": True}
        )
        .register_function(
            "home.prompt_mount.write", lambda execution, context: {"written": True}
        )
        .register_function(
            "core.context.inspect",
            lambda execution, context: {},
            executor_id="context.inspect",
        )
        .mark_actions_unsupported(
            "core.wait",
            "core.job.status",
            "core.job.stop",
            "core.job.wait",
            "core.ask",
            *EXECUTION_ACTIONS,
            "workspace.convert_with_markitdown",
            "workspace.convert_with_pypdf",
            "web.discover_pages",
            "web.fetch_with_defuddle",
            "web.fetch_with_trafilatura",
            "web.search_by_kimi",
        )
    )
    if workspace is None:
        builder = (
            builder.register_function(
                "workspace.delete", lambda execution, context: {"deleted": True}
            )
            .register_function(
                "workspace.describe", lambda execution, context: {"described": True}
            )
            .register_function(
                "workspace.edit", lambda execution, context: {"patched": True}
            )
            .register_function(
                "workspace.restore", lambda execution, context: {"restored": True}
            )
            .register_function(
                "workspace.trash_list", lambda execution, context: {"items": []}
            )
            .register_function(
                "workspace.list", lambda execution, context: {"scanned": True}
            )
            .register_function(
                "workspace.append", lambda execution, context: {"appended": True}
            )
            .register_function(
                "workspace.compose", lambda execution, context: {"created": True}
            )
            .mark_actions_unsupported(
                "core.wait",
                "core.job.status",
                "core.job.stop",
                "core.job.wait",
                "workspace.analyze",
                "workspace.write",
                "workspace.move",
                "workspace.mkdir",
                "workspace.tag",
                "workspace.read",
                "workspace.search",
            )
        )
    else:
        if workspace_context is None or workspace_bus is None or workspace_llm is None:
            raise AssertionError(
                "Real Workspace actions require Context, SignalBus, and LLM"
            )
        from tinysoul.infra.references import ReferenceResolver
        from tinysoul.kernel.retrieval.operations import SearchSession
        from tinysoul.kernel.retrieval.policy import RetrievalPolicy
        from tinysoul.kernel.retrieval.contracts import OperationKind, SourceKind

        async def workspace_source(request):
            return workspace.retrieval_corpus(request, references=ReferenceResolver())

        workspace_queries = SearchSession(
            action_id="workspace.search",
            retrieval_policies=(
                RetrievalPolicy(
                    "workspace.search", tuple(SourceKind), tuple(OperationKind)
                ),
            ),
            source=workspace_source,
        )
        register_workspace_actions(
            builder,
            workspace=WorkspaceService(workspace, queries=workspace_queries),
            tasks=action_tasks(workspace_context),
            llm=workspace_llm,
        )
    if memory is None:
        builder.register_function(
            "memory.search",
            lambda execution, context: {"items": []},
        ).register_function(
            "memory.memorize",
            lambda execution, context: {"digest": ""},
        ).register_function(
            "memory.inspect",
            lambda execution, context: {"text": ""},
        )
    else:
        from tinysoul.infra.references import ReferenceResolver
        from tinysoul.kernel.retrieval.operations import SearchSession
        from tinysoul.kernel.retrieval.policy import RetrievalPolicy
        from tinysoul.kernel.retrieval.contracts import SourceKind

        async def source(request):
            return memory.search_corpus(request, references=ReferenceResolver())

        queries = SearchSession(
            action_id="memory.search",
            retrieval_policies=(
                RetrievalPolicy("memory.search", (SourceKind.QUERY,), ()),
            ),
            source=source,
        )
        register_memory_actions(
            builder,
            memory=MemoryService(memory, queries=queries),
            runtime_bridge=RuntimeMemoryBridge(),
        )
    return builder.build()


def _tool_result(*tool_calls: ToolCallRecord) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="",
            model_id="fake",
            provider_id="fake",
            tool_calls=tool_calls,
        ),
        answer=None,
        tool_calls=tool_calls,
    )


def _json_result(value: JsonObject) -> TaskResult:
    return TaskResult.success(
        raw_response=RawResponse(
            answer_text="{}",
            model_id="fake",
            provider_id="fake",
        ),
        answer=JsonAnswer(value),
        tool_calls=(),
    )


def _task_failure(feedback: str) -> TaskResult:
    return TaskResult.failure_result(
        raw_response=RawResponse(
            answer_text="",
            model_id="fake",
            provider_id="fake",
        ),
        failure=TaskFailure(model_feedback=feedback),
    )


def _message_stack_text(stack: MessageStack) -> str:
    return "\n".join(
        part.text
        for message in stack.messages
        for part in message.parts
        if isinstance(part, TextPart)
    )


def _stack() -> MessageStack:
    return MessageStack()


def test_phase_prompt_content_preserves_scenario_and_skill_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tinysoul.kernel.context.prompts import PromptGuidance
    from tinysoul.kernel.loop.prompts import phase1_task_prompt, phase2_task_prompt
    from tinysoul.llm.protocol.messages import UserMessage
    from tinysoul.prompts.kernel import loop as prompt_text

    monkeypatch.setattr(prompt_text, "PHASE1_GUIDANCE", ("phase one {literal}",))
    monkeypatch.setattr(prompt_text, "PHASE2_GUIDANCE", ("phase two {literal}",))
    scenario = "scenario {instruction}"
    feedback = "feedback {detail}"
    skill = PromptGuidance("skill {body}", "home:mount/domain/core", "home")
    first = phase1_task_prompt(
        domain_prompt="domain {data}",
        turn_guidance=(scenario,),
        feedback=(feedback,),
    )
    second = phase2_task_prompt(
        selected_domains=("core",),
        domain_skills=(skill,),
        turn_guidance=(scenario,),
        feedback=(feedback,),
    )
    for prompt, marker in (
        (first, "phase one {literal}"),
        (second, "phase two {literal}"),
    ):
        assert all(
            isinstance(message, UserMessage) for message in prompt.render_messages()
        )
        parts = prompt.guide_blocks[0].message.parts
        text = "".join(part.text for part in parts if isinstance(part, TextPart))
        assert text.index(marker) < text.index(scenario) < text.index(feedback)
    assert len(first.guide_blocks) == 1
    assert second.guide_blocks[1].owner == skill.owner
    assert second.guide_blocks[1].refs == (skill.reference,)
    assert second.provenance()[1].message_indices == (1,)
