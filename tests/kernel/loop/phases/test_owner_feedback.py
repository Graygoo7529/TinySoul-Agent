from __future__ import annotations
from datetime import date as CalendarDate
from datetime import date
from pathlib import Path
from tinysoul.kernel.context import ContextEngineBuilder
from tinysoul.kernel.context.builtin.trace import TraceKind
from tinysoul.llm.protocol.messages import JsonPart
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.kernel.loop import Phase1Unit, Phase3Unit
from tinysoul.plugins.memory import DailyMemoryDocument, MemoryEngine, MemorySettings
from tinysoul.runtime import CyclePhase, RunLevel, RunScope, SignalBus
from tinysoul.plugins.workspace import WorkspaceEngineBuilder, WorkspaceSettings
from tests.kernel.loop.phases.support import (
    FakeLLM,
    _action_engine,
    _json_result,
    _tool_result,
)


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
