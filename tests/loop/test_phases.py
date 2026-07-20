from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from tinysoul.action import ActionEngine, ActionEngineBuilder
from tinysoul.action.backends import LLMActionTaskRunner
from tinysoul.capabilities.script import SCRIPT_ACTIONS
from tinysoul.capabilities.shell import SHELL_ACTIONS
from tinysoul.context import (
    BackgroundCatalog,
    BackgroundCatalogItem,
    ContextEngine,
    ContextEngineBuilder,
    WorkspaceSnapshot,
    build_workspace_sync_signal,
)
from tinysoul.context.trace import TraceKind
from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import JsonPart, MessageStack, TextPart
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import JsonAnswer, RawResponse, TaskFailure, TaskResult
from tinysoul.llm.tools import ToolCallRecord, ToolKind, ToolUse
from tinysoul.loop import LoopTraceNoteKind, Phase1Unit, Phase2Unit, Phase3Unit
from tinysoul.memory import (
    MemoryEngine,
    MemoryLink,
    MemorySettings,
    register_memory_actions,
)
from tinysoul.memory.store import MemoryStore
from tinysoul.runtime import (
    RUNTIME_TURN_END,
    RUNTIME_TURN_OUTPUT,
    CyclePhase,
    RunLevel,
    RunScope,
    RuntimeException,
    SignalBus,
    ObservationEvent,
    ObservationLevel,
)
from tinysoul.runtime.bridge import RuntimeMemoryBridge
from tinysoul.workspace import (
    WorkspaceEngine,
    WorkspaceEngineBuilder,
    WorkspaceSettings,
    register_workspace_actions,
)


class FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self.results.popleft()


@dataclass
class RecordingObservations:
    events: list[ObservationEvent] = field(default_factory=list)

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)


def test_phase_units_select_normalize_execute_and_trace_answer() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now")
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
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
    )
    phase1_scope = base_scope.push(RunLevel.PHASE, CyclePhase.PHASE1.value)
    phase2_scope = base_scope.push(RunLevel.PHASE, CyclePhase.PHASE2.value)
    phase3_scope = base_scope.push(RunLevel.PHASE, CyclePhase.PHASE3.value)

    phase1 = Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=2,
    ).run(scope=phase1_scope, cycle_id="cycle_1")
    phase2 = Phase2Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=2,
        observations=observations,
    ).run(
        selected_domains=phase1.selected_domains,
        scope=phase2_scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )
    with pytest.raises(RuntimeException) as raised:
        Phase3Unit(
            context=context,
            action=action,
            bus=bus,
            observations=observations,
        ).run(
            normalization=phase2.normalization,
            scope=phase3_scope,
            cycle_id="cycle_1",
            turn_id=turn_id,
        )

    assert phase1.selected_domains == ("core",)
    assert phase2.normalization.calls[0].action_name == "core.answer"
    assert raised.value.reason == RUNTIME_TURN_OUTPUT
    assert raised.value.payload["text"] == "done"
    assert str(raised.value.payload["result_id"]).startswith("action_result_")
    assert context.trace_kinds() == (
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
    assert action_events[0].payload["call_id"] == "answer_1"
    assert action_events[1].payload["call_id"] == "answer_1"


def test_phase1_how_catalog_and_load_background_feed_phase2_only_for_the_turn() -> None:
    class _HowProvider:
        def catalog(self, business_day: date) -> BackgroundCatalog:
            return BackgroundCatalog(
                owner="home",
                loadable_links=("home:how@review",),
                items=(
                    BackgroundCatalogItem(
                        link="home:how@review",
                        title="Review Home",
                        description="Review effective Home changes.",
                    ),
                ),
            )

        def load(self, link: str, business_day: date) -> str:
            assert link == "home:how@review"
            return "HOW BODY: compare runtime and actual Home."

    context = (
        ContextEngineBuilder(system_text="sys")
        .add_background_provider(_HowProvider())
        .build()
    )
    turn_id = context.begin_turn("review Home")
    context.prepare_default_background(date(2026, 7, 14))
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
                    arguments={"links": ["home:how@review"]},
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
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
    )

    phase1 = Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=1,
    ).run(
        scope=base_scope.push(RunLevel.PHASE, CyclePhase.PHASE1.value),
        cycle_id="cycle_1",
    )
    Phase2Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=1,
    ).run(
        selected_domains=phase1.selected_domains,
        scope=base_scope.push(RunLevel.PHASE, CyclePhase.PHASE2.value),
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    phase1_stack = llm.calls[0].messages
    catalog = next(
        message
        for message in phase1_stack.messages
        if message.label == "background:catalog:home"
    )
    assert isinstance(catalog.parts[0], JsonPart)
    assert catalog.parts[0].value["items"] == [
        {
            "link": "home:how@review",
            "title": "Review Home",
            "description": "Review effective Home changes.",
        }
    ]
    assert "HOW BODY" not in _message_stack_text(phase1_stack)

    phase2_stack = llm.calls[1].messages
    loaded = next(
        message
        for message in phase2_stack.messages
        if message.label == "background:home:how@review"
    )
    assert isinstance(loaded.parts[0], TextPart)
    assert loaded.parts[0].text == "HOW BODY: compare runtime and actual Home."

    context.complete_preparation()
    context.end_turn()
    context.begin_turn("next turn")
    context.prepare_default_background(date(2026, 7, 14))
    assert "home:how@review" not in context.background_links()


def test_real_memory_actions_record_turn_trace_without_background_mutation(
    tmp_path: Path,
) -> None:
    memory_root = tmp_path / "memory"
    MemoryStore(root=memory_root, max_document_chars=16000).write(
        MemoryLink.parse("memory:2026-07-13"),
        "free-form remembered fact",
    )

    class HomeCatalog:
        def actual_top_links(self) -> tuple[str, ...]:
            return ()

    memory = MemoryEngine(
        settings=MemorySettings(root=memory_root),
        home_catalog=HomeCatalog(),
    )
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("recall yesterday")
    action = _action_engine(memory=memory)
    normalization = action.normalize(
        (
            ToolCallRecord(
                id="recall_1",
                name="memory.recall",
                arguments={"memory_link": "memory:2026-07-13"},
                kind=ToolKind.ACTION,
            ),
            ToolCallRecord(
                id="search_1",
                name="memory.search",
                arguments={"query": "remembered"},
                kind=ToolKind.ACTION,
            ),
        )
    )
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )

    outcome = Phase3Unit(
        context=context,
        action=action,
        bus=SignalBus(),
    ).run(
        normalization=normalization,
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert outcome.results[0].payload["text"] == "free-form remembered fact"
    items = outcome.results[1].payload["items"]
    assert isinstance(items, list)
    first_item = items[0]
    assert isinstance(first_item, dict)
    assert first_item["link"] == "memory:2026-07-13"
    assert "period" not in first_item
    assert context.trace_kinds() == (
        TraceKind.ACTION_RESULT,
        TraceKind.ACTION_RESULT,
    )
    assert context.background_links() == ()


def test_real_workspace_inspection_actions_preserve_trace_lifecycle(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "a.md").write_text("alpha needle\n", encoding="utf-8")
    (workspace_root / "b.md").write_text("beta\n", encoding="utf-8")
    workspace = WorkspaceEngineBuilder(WorkspaceSettings(root=workspace_root)).build()
    workspace.reconcile()

    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("inspect workspace")
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
                    "link": "workspace:a.md",
                    "start_line": 1,
                    "end_line": 1,
                },
                kind=ToolKind.ACTION,
            ),
            ToolCallRecord(
                id="search_1",
                name="workspace.search_text",
                arguments={
                    "query": "needle",
                    "scope": {"kind": "workspace"},
                },
                kind=ToolKind.ACTION,
            ),
            ToolCallRecord(
                id="analyze_1",
                name="workspace.analyze",
                arguments={
                    "intent": "Compare the selected files.",
                    "reference_links": ["workspace:a.md", "workspace:b.md"],
                },
                kind=ToolKind.ACTION,
            ),
        )
    )
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )

    outcome = Phase3Unit(context=context, action=action, bus=bus).run(
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
    assert len(entries) == 3
    for entry in entries[:2]:
        assert entry.visible_overlay is not None
        assert isinstance(entry.visible_overlay.parts[0], JsonPart)
        assert isinstance(entry.message.parts[0], JsonPart)
        assert "alpha needle" in str(entry.visible_overlay.parts[0].value)
        assert "alpha needle" not in str(entry.message.parts[0].value)
    assert entries[2].visible_overlay is None
    assert isinstance(entries[2].message.parts[0], JsonPart)
    analyze_payload = entries[2].message.parts[0].value["payload"]
    assert isinstance(analyze_payload, dict)
    assert analyze_payload["answer"] == (
        "Alpha and beta are present."
    )
    assert context.fold_trace_overlays() == 2
    assert all(entry.visible_overlay is None for entry in context.seal_trace().entries)

    summary = context.end_turn()
    assert "alpha needle" not in str(summary.trace)
    assert "Alpha and beta are present." in str(summary.trace)


def test_phase1_retries_invalid_domain_selection() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("answer now")
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
    scope = RunScope().push(RunLevel.PHASE, CyclePhase.PHASE1.value)

    outcome = Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=2,
    ).run(scope=scope, cycle_id="cycle_1")

    assert outcome.selected_domains == ("core",)
    assert outcome.attempts == 2


def test_phase1_prompt_requires_same_response_working_reconciliation() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("finish current work")
    action = _action_engine()
    llm = FakeLLM(
        (
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

    Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=SignalBus(),
        retry_limit=1,
    ).run(
        scope=RunScope().push(RunLevel.PHASE, CyclePhase.PHASE1.value),
        cycle_id="cycle_1",
    )

    prompt = _message_stack_text(llm.calls[0].messages)
    assert "reconcile existing WorkingContext" in prompt
    assert "call update_working in this same Phase1 response" in prompt
    assert "mark every current-goal todo done or cancelled" in prompt


def test_phase1_applies_working_reconciliation_before_returning() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("finish current work")
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
                    name="update_working",
                    arguments={
                        "set_todos": [
                            {
                                "key": "report",
                                "content": "Write the report",
                                "status": "in_progress",
                            }
                        ]
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
                    name="update_working",
                    arguments={
                        "set_todos": [
                            {
                                "key": "report",
                                "content": "Write the report",
                                "status": "done",
                            }
                        ]
                    },
                    kind=ToolKind.CONTROL,
                ),
            ),
        )
    )
    turn_scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
    )
    unit = Phase1Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=1,
    )

    outcome_1 = unit.run(
        scope=turn_scope.push(RunLevel.CYCLE, "cycle_1").push(
            RunLevel.PHASE, CyclePhase.PHASE1.value
        ),
        cycle_id="cycle_1",
    )
    outcome = unit.run(
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


def test_phase1_maps_loop_scope_failure_to_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    context.begin_turn("answer now")
    action = _action_engine()
    duplicate_scope = context.control_scope()
    monkeypatch.setattr(
        ActionEngine,
        "phase1_scope",
        lambda _self: duplicate_scope,
    )

    with pytest.raises(RuntimeException) as raised:
        Phase1Unit(
            context=context,
            action=action,
            llm=FakeLLM(()),
            bus=SignalBus(),
            retry_limit=2,
        ).run(
            scope=RunScope().push(RunLevel.PHASE, CyclePhase.PHASE1.value),
            cycle_id="cycle_1",
        )

    assert raised.value.reason == RUNTIME_TURN_END
    assert raised.value.payload["kind"] == "loop.contract_violation"


def test_phase2_records_note_when_task_failures_exhaust_retries() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now")
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
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE2.value)
    )

    outcome = Phase2Unit(
        context=context,
        action=action,
        llm=llm,
        bus=bus,
        retry_limit=2,
    ).run(
        selected_domains=("core",),
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert outcome.normalization.calls == ()
    assert outcome.attempts == 2
    assert context.trace_kinds() == (
        TraceKind.PHASE_NOTE,
    )


def test_phase3_records_multiple_answers_as_loop_note() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("answer now")
    action = _action_engine()
    bus = SignalBus()
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
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

    outcome = Phase3Unit(context=context, action=action, bus=bus).run(
        normalization=normalization,
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )
    summary = context.end_turn()

    assert len(outcome.results) == 2
    assert outcome.phase_results == ()
    assert context.turn_active is False
    note_message = summary.trace[-1]["message"]
    assert isinstance(note_message, dict)
    content = note_message["content"]
    assert isinstance(content, list)
    note_part = content[0]
    assert isinstance(note_part, dict)
    note = note_part["value"]
    assert isinstance(note, dict)
    assert note["kind"] == LoopTraceNoteKind.MULTIPLE_TURN_OUTPUTS.value
    result_ids = note["result_ids"]
    assert isinstance(result_ids, list)
    assert len(result_ids) == 2


def test_phase3_ignores_stale_workspace_sync_failure_from_another_call() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("reason now")
    action = _action_engine()
    bus = SignalBus()
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )
    old_scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "old_turn")
    )
    bus.emit(
        build_workspace_sync_signal(
            WorkspaceSnapshot(revision=1),
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

    outcome = Phase3Unit(context=context, action=action, bus=bus).run(
        normalization=normalization,
        scope=scope,
        cycle_id="cycle_1",
        turn_id=turn_id,
    )

    assert outcome.results[0].status.value == "success"


def test_phase3_rejects_failed_sync_for_current_workspace_action() -> None:
    context = ContextEngineBuilder(system_text="sys").build()
    turn_id = context.begin_turn("scan now")
    bus = SignalBus()
    old_scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "old_turn")
    )

    def emit_invalid_sync(execution, execution_context):
        signal_bus = execution_context.signal_bus
        assert signal_bus is not None
        signal_bus.emit(
            build_workspace_sync_signal(
                WorkspaceSnapshot(revision=1),
                call_id=execution.call.call_id,
                scope=old_scope,
                source="test.current",
            )
        )
        return {"scanned": True}

    action = (
        ActionEngineBuilder(Path("tinysoul/action/catalog"))
        .register_native("context.trace.fold", lambda execution, context: {})
        .register_native("context.trace.inspect", lambda execution, context: {})
        .register_native("context.trace.recall", lambda execution, context: {})
        .register_native("core.answer", lambda execution, context: {"text": "done"})
        .register_native("core.reason", lambda execution, context: {"ok": True})
        .register_native("home.resource.delete", lambda execution, context: {"deleted": True})
        .register_native("home.resource.patch", lambda execution, context: {"patched": True})
        .register_native("home.resource.read", lambda execution, context: {"read": True})
        .register_native("home.resource.write", lambda execution, context: {"written": True})
        .register_native("home.top.delete", lambda execution, context: {"deleted": True})
        .register_native("home.top.patch", lambda execution, context: {"patched": True})
        .register_native("home.top.write", lambda execution, context: {"written": True})
        .register_native("home.top.search", lambda execution, context: {"items": []})
        .register_native("memory.recall", lambda execution, context: {"text": ""})
        .register_native("memory.search", lambda execution, context: {"items": []})
        .register_native("home.prompt_mount.patch", lambda execution, context: {"patched": True})
        .register_native("home.prompt_mount.write", lambda execution, context: {"written": True})
        .register_native("session.history.inspect", lambda execution, context: {})
        .register_native("session.history.recall", lambda execution, context: {})
        .register_native("workspace.delete", lambda execution, context: {"deleted": True})
        .register_native("workspace.describe", lambda execution, context: {"described": True})
        .register_native("workspace.patch", lambda execution, context: {"patched": True})
        .register_native("workspace.restore", lambda execution, context: {"restored": True})
        .register_native("workspace.trash.list", lambda execution, context: {"items": []})
        .register_native("workspace.scan", emit_invalid_sync)
        .register_native("workspace.write", lambda execution, context: {"written": True})
        .register_native("workspace.rewrite", lambda execution, context: {"rewritten": True})
        .disable_actions(
            *SCRIPT_ACTIONS,
            *SHELL_ACTIONS,
            "resource.convert_with_markitdown",
            "resource.convert_with_pypdf",
            "web.discover_pages",
            "web.fetch_with_defuddle",
            "web.fetch_with_trafilatura",
            "web.search_by_kimi",
            "workspace.analyze",
            "workspace.read",
            "workspace.search_text",
        )
        .build()
    )
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, turn_id)
        .push(RunLevel.CYCLE, "cycle_1")
        .push(RunLevel.PHASE, CyclePhase.PHASE3.value)
    )
    normalization = action.normalize(
        (
            ToolCallRecord(
                id="scan_1",
                name="workspace.scan",
                arguments={},
                kind=ToolKind.ACTION,
            ),
        )
    )

    with pytest.raises(RuntimeException) as raised:
        Phase3Unit(context=context, action=action, bus=bus).run(
            normalization=normalization,
            scope=scope,
            cycle_id="cycle_1",
            turn_id=turn_id,
        )

    assert raised.value.payload["kind"] == "loop.contract_violation"


def _action_engine(
    *,
    memory: MemoryEngine | None = None,
    workspace: WorkspaceEngine | None = None,
    workspace_context: ContextEngine | None = None,
    workspace_bus: SignalBus | None = None,
    workspace_llm: FakeLLM | None = None,
) -> ActionEngine:
    builder = (
        ActionEngineBuilder(Path("tinysoul/action/catalog"))
        .register_native("context.trace.fold", lambda execution, context: {})
        .register_native("context.trace.inspect", lambda execution, context: {})
        .register_native("context.trace.recall", lambda execution, context: {})
        .register_native("core.answer", lambda execution, context: {"text": "done"})
        .register_native("core.reason", lambda execution, context: {"ok": True})
        .register_native("home.resource.delete", lambda execution, context: {"deleted": True})
        .register_native("home.resource.patch", lambda execution, context: {"patched": True})
        .register_native("home.resource.read", lambda execution, context: {"read": True})
        .register_native("home.resource.write", lambda execution, context: {"written": True})
        .register_native("home.top.delete", lambda execution, context: {"deleted": True})
        .register_native("home.top.patch", lambda execution, context: {"patched": True})
        .register_native("home.top.write", lambda execution, context: {"written": True})
        .register_native("home.top.search", lambda execution, context: {"items": []})
        .register_native("home.prompt_mount.patch", lambda execution, context: {"patched": True})
        .register_native("home.prompt_mount.write", lambda execution, context: {"written": True})
        .register_native("session.history.inspect", lambda execution, context: {})
        .register_native("session.history.recall", lambda execution, context: {})
        .disable_actions(
            *SCRIPT_ACTIONS,
            *SHELL_ACTIONS,
            "resource.convert_with_markitdown",
            "resource.convert_with_pypdf",
            "web.discover_pages",
            "web.fetch_with_defuddle",
            "web.fetch_with_trafilatura",
            "web.search_by_kimi",
        )
    )
    if workspace is None:
        builder = (
            builder.register_native(
                "workspace.delete", lambda execution, context: {"deleted": True}
            )
            .register_native(
                "workspace.describe", lambda execution, context: {"described": True}
            )
            .register_native(
                "workspace.patch", lambda execution, context: {"patched": True}
            )
            .register_native(
                "workspace.restore", lambda execution, context: {"restored": True}
            )
            .register_native(
                "workspace.trash.list", lambda execution, context: {"items": []}
            )
            .register_native(
                "workspace.scan", lambda execution, context: {"scanned": True}
            )
            .register_native(
                "workspace.write", lambda execution, context: {"written": True}
            )
            .register_native(
                "workspace.rewrite", lambda execution, context: {"rewritten": True}
            )
            .disable_actions(
                "workspace.analyze",
                "workspace.read",
                "workspace.search_text",
            )
        )
    else:
        if workspace_context is None or workspace_bus is None or workspace_llm is None:
            raise AssertionError("Real Workspace actions require Context, SignalBus, and LLM")
        register_workspace_actions(
            builder,
            workspace=workspace,
            bus=workspace_bus,
            llm_action=LLMActionTaskRunner(
                llm_runner=workspace_llm,
                context=workspace_context,
            ),
        )
    if memory is None:
        builder.register_native(
            "memory.recall",
            lambda execution, context: {"text": ""},
        ).register_native(
            "memory.search",
            lambda execution, context: {"items": []},
        )
    else:
        register_memory_actions(
            builder,
            memory=memory,
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
