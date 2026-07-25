"""Session persistence, summarization, and Turn projection tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
from pathlib import Path

import pytest

from tinysoul.action import (
    ActionCatalog,
    ActionCall,
    ActionExecution,
    ActionExecutionContext,
    ActionFramework,
    ActionResultStatus,
    builtin_action_catalog_root,
)
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.action.core.rendering import ActionResultRenderer
from tinysoul.context import (
    ContextEngineBuilder,
    ContextSignalBatch,
    TurnSummary,
    build_trace_action_result_signal,
    canonical_trace_digest,
)
from tinysoul.context.prompts import PromptBlock, TaskPrompt
from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.loop import BusinessDay, TurnPreparationRequest
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.runtime.bridge import RuntimeSessionBridge
from tinysoul.session import (
    SessionEngine,
    SessionHistoryFailureReason,
    SessionHistoryRequestError,
    SessionIOError,
    SessionInvariantError,
    SessionSettings,
    project_turn_actions,
)
from tinysoul.session.store import SessionStore
from tinysoul.session.actions import (
    SessionHistoryActionsExecutor,
    SessionHistoryInspectExecutor,
    SessionHistoryRecallExecutor,
)
from tinysoul.session.models import SessionHistoryKind, SessionRecord
from tinysoul.session.projection import SessionTurnPreparationHandler


DAY = BusinessDay.parse("2026-07-12")


def test_session_persists_turns_and_builds_hierarchical_summary(tmp_path: Path) -> None:
    settings = _settings(tmp_path, background_max_chars=900)
    session = _engine(settings)

    for index in range(3):
        _record_turn(
            session,
            summary=_summary(f"turn_{index}", ask=f"question {index}"),
            output={
                "text": f"answer {index} " + "x" * 700,
                "result_id": f"answer_{index}",
                "references": [],
                "metadata": {},
            },
            exhausted=False,
        )

    head = session.inspect_history()
    items = head["items"]
    assert isinstance(items, list)
    assert len(items) == 2
    summary_header = items[0]
    assert isinstance(summary_header, dict)
    assert summary_header["kind"] == "summary"
    assert summary_header["child_count"] == 2

    summary_ref = summary_header["ref"]
    assert isinstance(summary_ref, str)
    inspected_summary = session.inspect_history(summary_ref)
    child_items = inspected_summary["items"]
    assert isinstance(child_items, list)
    assert [item["ref"] for item in child_items if isinstance(item, dict)] == [
        "session:turn/turn_0",
        "session:turn/turn_1",
    ]
    with pytest.raises(SessionHistoryRequestError) as failure:
        session.recall_history(summary_ref)
    assert failure.value.reason is SessionHistoryFailureReason.WRONG_RECORD_KIND
    recalled_turn = session.recall_history("session:turn/turn_0", max_chars=4000)
    source = recalled_turn["source"]
    assert isinstance(source, dict)
    assert source["ref"] == "session:turn/turn_0"
    assert "background" not in recalled_turn
    assert "preview" not in recalled_turn

    reloaded = _engine(settings)
    assert reloaded.revision == session.revision
    assert reloaded.inspect_history()["items"] == items


def test_session_background_is_prepared_before_home_background(tmp_path: Path) -> None:
    session = _engine(_settings(tmp_path))
    _record_turn(
        session,
        summary=_summary("turn_previous", ask="earlier question"),
        output={
            "text": "earlier answer",
            "result_id": "answer_previous",
            "references": [],
            "metadata": {},
        },
        exhausted=False,
    )
    context = (
        ContextEngineBuilder(system_text="system")
        .add_default_background("home:agent@AGENT", "agent home")
        .build()
    )
    turn_id = context.begin_turn("current question")
    context.prepare_default_background(date(2026, 7, 14))
    scope = RunScope().push(RunLevel.PROGRAM, "program").push(RunLevel.TURN, turn_id)
    request = TurnPreparationRequest(
        turn_id=turn_id,
        user_input="current question",
        business_day=DAY,
        scope=scope,
    )
    signals = SessionTurnPreparationHandler(session).prepare(request)

    assert context.consume_signal_batch(
        ContextSignalBatch(turn_id=turn_id, signals=signals)
    ) == ()
    context.complete_preparation()
    stack = context.compose(
        TaskPrompt(
            guide_blocks=(PromptBlock.from_text("guide", "continue"),),
        )
    )
    labels = tuple(message.label for message in stack.messages)
    assert labels.index("background:session:turn_previous") < labels.index(
        "background:home:agent@AGENT"
    )
    late_results = context.consume_signal_batch(
        ContextSignalBatch(turn_id=turn_id, signals=signals)
    )
    assert len(late_results) == 1
    assert "preparation" in late_results[0].model_feedback


def test_session_inspect_action_enters_trace_without_changing_background(
    tmp_path: Path,
) -> None:
    session = _engine(_settings(tmp_path))
    _record_turn(
        session,
        summary=_summary("turn_previous", ask="earlier question"),
        output={"text": "earlier answer"},
        exhausted=False,
    )
    context = ContextEngineBuilder(system_text="system").build()
    turn_id = context.begin_turn("find the earlier turn")
    scope = RunScope().push(RunLevel.PROGRAM, "program").push(RunLevel.TURN, turn_id)
    signals = SessionTurnPreparationHandler(session).prepare(
        TurnPreparationRequest(
            turn_id=turn_id,
            user_input="find the earlier turn",
            business_day=DAY,
            scope=scope,
        )
    )
    assert context.consume_signal_batch(
        ContextSignalBatch(turn_id=turn_id, signals=signals)
    ) == ()
    context.complete_preparation()
    before = session.background_snapshot(DAY)

    with builtin_action_catalog_root() as root:
        action = ActionCatalogLoader().load(root).get_action(
            "session.history.inspect"
        )
    execution = ActionExecution(
        action=action,
        call=ActionCall(
            call_id="inspect_1",
            action_name="session.history.inspect",
            params={},
            sequence=1,
        ),
        framework=ActionFramework(
            invoke_id="invoke_1",
            batch_id="batch_1",
            scope=scope,
            domain="session",
            turn_id=turn_id,
            cycle_id="cycle_1",
        ),
    )
    result = SessionHistoryInspectExecutor(
        session,
        runtime_bridge=RuntimeSessionBridge(),
    ).execute(execution, ActionExecutionContext())
    assert result.status is ActionResultStatus.SUCCESS
    rendered = ActionResultRenderer().render_tool_result(result)
    signal = build_trace_action_result_signal(
        rendered.visible_message,
        scope=scope,
        source="loop.phase3",
        cycle_id="cycle_1",
    )

    assert context.consume_signal_batch(
        ContextSignalBatch(turn_id=turn_id, signals=(signal,))
    ) == ()
    assert session.background_snapshot(DAY) == before
    stack = context.compose(
        TaskPrompt(guide_blocks=(PromptBlock.from_text("guide", "continue"),))
    )
    labels = tuple(message.label for message in stack.messages)
    assert labels.count("background:session:turn_previous") == 1
    assert "action_result" in labels
    summary = context.end_turn()
    assert summary.trace[0]["kind"] == "action_result"


def test_session_recall_action_preserves_engine_wrong_kind_failure(
    tmp_path: Path,
) -> None:
    session = _engine(_settings(tmp_path, background_max_chars=900))
    for index in range(3):
        _record_turn(
            session,
            summary=_summary(f"turn_kind_{index}", ask=f"question {index}"),
            output={"text": "answer " + "x" * 700},
            exhausted=False,
        )
    items = session.inspect_history()["items"]
    assert isinstance(items, list)
    summary_item = items[0]
    assert isinstance(summary_item, dict)
    summary_ref = summary_item["ref"]
    assert isinstance(summary_ref, str)
    with builtin_action_catalog_root() as root:
        action = ActionCatalogLoader().load(root).get_action(
            "session.history.recall"
        )
    execution = ActionExecution(
        action=action,
        call=ActionCall(
            call_id="recall_summary",
            action_name="session.history.recall",
            params={"ref": summary_ref},
            sequence=1,
        ),
        framework=ActionFramework(
            invoke_id="invoke_recall",
            batch_id="batch_recall",
            scope=RunScope(),
            domain="session",
        ),
    )

    result = SessionHistoryRecallExecutor(
        session,
        runtime_bridge=RuntimeSessionBridge(),
    ).execute(execution, ActionExecutionContext())

    assert result.status is ActionResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason == SessionHistoryFailureReason.WRONG_RECORD_KIND.value
    assert result.failure.scope == "session.history.recall"


def test_session_projects_compact_per_action_outcomes_to_context(tmp_path: Path) -> None:
    session = _engine(_settings(tmp_path))
    trace = (
        _decision_entry("call_reason", "core.reason", {"topic": "design"}),
        _decision_entry("call_scan", "workspace.scan", {}),
        _result_entry("call_reason", "core.reason", {"conclusion": "keep it"}),
        _result_entry("call_scan", "workspace.scan", {"count": 2}),
    )
    summary = TurnSummary(
        turn_id="turn_actions",
        inputs=({"input_id": "input_1", "text": "analyze", "merged": True},),
        trace=trace,
        trace_digest=canonical_trace_digest(trace),
        trace_summary={
            "entry_count": 4,
            "action_names": ["core.reason", "workspace.scan"],
        },
    )

    _record_turn(session, summary=summary, output={"text": "done"}, exhausted=False)

    snapshot = session.background_snapshot(DAY)
    background = snapshot.items[0].content
    assert background == {
        "kind": "session_turn",
        "ref": "session:turn/turn_actions",
        "user_ask": ["analyze"],
        "answer": "done",
        "references": [],
        "exhausted": False,
        "action_outcomes": [
            {
                "action": "core.reason",
                "success_count": 1,
                "failed_count": 0,
                "timeout_count": 0,
            },
            {
                "action": "workspace.scan",
                "success_count": 1,
                "failed_count": 0,
                "timeout_count": 0,
            },
        ],
    }

    persisted_items = session.inspect_history("session:turn/turn_actions")["items"]
    assert isinstance(persisted_items, list)
    persisted_preview = persisted_items[0]
    assert isinstance(persisted_preview, dict)
    preview = persisted_preview["preview"]
    assert isinstance(preview, dict)
    assert preview["trace_digest"] == canonical_trace_digest(trace)
    assert preview["trace_summary"] == {
        "entry_count": 4,
        "action_names": ["core.reason", "workspace.scan"],
    }
    selected = preview["actions"]
    assert isinstance(selected, list) and len(selected) == 1
    selected_action = selected[0]
    assert isinstance(selected_action, dict)
    assert selected_action["action"] == "core.reason"


def test_session_action_model_projection_hides_integrity_metadata(
    tmp_path: Path,
) -> None:
    session = _engine(_settings(tmp_path))
    trace = (
        _decision_entry("call_scan", "workspace.scan", {}),
        _result_entry("call_scan", "workspace.scan", {"count": 2}),
    )
    _record_turn(
        session,
        summary=TurnSummary(
            turn_id="turn_model_projection",
            inputs=({"input_id": "input_1", "text": "scan", "merged": True},),
            trace=trace,
            trace_digest=canonical_trace_digest(trace),
        ),
        output={"text": "done"},
        exhausted=False,
    )
    ref = "session:turn/turn_model_projection"
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)

    inspect = SessionHistoryInspectExecutor(
        session,
        runtime_bridge=RuntimeSessionBridge(),
    ).execute(
        _history_execution(catalog, "session.history.inspect", {"ref": ref}),
        ActionExecutionContext(),
    )
    recall = SessionHistoryRecallExecutor(
        session,
        runtime_bridge=RuntimeSessionBridge(),
    ).execute(
        _history_execution(catalog, "session.history.recall", {"ref": ref}),
        ActionExecutionContext(),
    )
    actions = SessionHistoryActionsExecutor(
        session,
        runtime_bridge=RuntimeSessionBridge(),
    ).execute(
        _history_execution(catalog, "session.history.actions", {"ref": ref}),
        ActionExecutionContext(),
    )

    for result in (inspect, recall, actions):
        assert result.status is ActionResultStatus.SUCCESS
        source = result.payload["source"]
        assert isinstance(source, dict)
        assert "revision" not in source
        assert "trace_digest" not in source
    action_summary = actions.payload["summary"]
    assert isinstance(action_summary, dict)
    assert "trace_digest" not in action_summary
    inspect_items = inspect.payload["items"]
    assert isinstance(inspect_items, list)
    inspect_item = inspect_items[0]
    assert isinstance(inspect_item, dict)
    inspect_preview = inspect_item["preview"]
    assert isinstance(inspect_preview, dict)
    assert "trace_digest" not in inspect_preview

    persisted_source = session.recall_history(ref)["source"]
    assert isinstance(persisted_source, dict)
    assert persisted_source["trace_digest"] == canonical_trace_digest(trace)


def test_action_projector_preserves_orphan_result_location() -> None:
    result = _result_entry("orphan", "workspace.scan", {"count": 1})
    result["cycle_id"] = "cycle_7"
    trace = (result,)

    projection = project_turn_actions(
        trace,
        expected_digest=canonical_trace_digest(trace),
    )

    detail = projection.details[0]
    assert detail.pairing_issue is not None
    assert detail.pairing_issue.value == "orphan_result"
    assert detail.cycle_id == "cycle_7"
    assert detail.phase == "phase3"


def test_action_projector_splits_name_mismatch_by_real_action() -> None:
    trace = (
        _decision_entry("call_mismatch", "workspace.scan", {}),
        _result_entry("call_mismatch", "workspace.read", {"link": "workspace:a"}),
    )

    projection = project_turn_actions(
        trace,
        expected_digest=canonical_trace_digest(trace),
    )

    assert len(projection.details) == 2
    assert projection.pairing_issue_count == 2
    assert projection.unmatched_call_count == 1
    assert projection.unmatched_result_count == 1
    assert [item.action_name for item in projection.details] == [
        "workspace.scan",
        "workspace.read",
    ]
    assert projection.background_outcomes() == (
        {
            "action": "workspace.read",
            "success_count": 1,
            "failed_count": 0,
            "timeout_count": 0,
            "incomplete_count": 1,
        },
        {
            "action": "workspace.scan",
            "success_count": 0,
            "failed_count": 0,
            "timeout_count": 0,
            "incomplete_count": 1,
        },
    )
    by_action = {item["action"]: item for item in projection.by_action()}
    assert by_action["workspace.scan"]["calls"] == 1
    assert by_action["workspace.scan"]["results"] == 0
    assert by_action["workspace.read"]["calls"] == 0
    assert by_action["workspace.read"]["results"] == 1
    assert by_action["workspace.read"]["success"] == 1


def test_session_turn_recall_uses_bounded_continuation_cursor(tmp_path: Path) -> None:
    settings = replace(_settings(tmp_path), history_page_max_chars=1800)
    session = _engine(settings)
    trace: tuple[JsonObject, ...] = tuple(
        {"entry_id": f"entry_{index}", "detail": "x" * 500}
        for index in range(3)
    )
    _record_turn(
        session,
        summary=TurnSummary(
            turn_id="turn_paged",
            inputs=({"input_id": "input_1", "text": "page", "merged": True},),
            trace=trace,
            trace_digest=canonical_trace_digest(trace),
        ),
        output={"text": "done"},
        exhausted=False,
    )

    first = session.recall_history(
        "session:turn/turn_paged",
        max_chars=10000,
    )
    next_cursor = first["next_cursor"]
    assert isinstance(next_cursor, dict)
    source = first["source"]
    assert isinstance(source, dict)
    assert source["owner"] == "session"
    assert source["turn_id"] == "turn_paged"
    assert source["trace_digest"] == canonical_trace_digest(trace)
    next_entry_index = next_cursor["entry_index"]
    assert isinstance(next_entry_index, int)
    assert next_entry_index >= 1
    second = session.recall_history(
        "session:turn/turn_paged",
        cursor=next_cursor,
    )
    assert second["cursor"] == next_cursor
    coverage = second["entry_coverage"]
    assert isinstance(coverage, list)
    assert coverage[0] == next_entry_index


def test_session_recall_honors_exact_entry_limit(tmp_path: Path) -> None:
    session = _engine(_settings(tmp_path))
    trace: tuple[JsonObject, ...] = tuple(
        {"entry_id": f"entry_{index}", "detail": f"value {index}"}
        for index in range(3)
    )
    _record_turn(
        session,
        summary=TurnSummary(
            turn_id="turn_exact_entry",
            inputs=({"input_id": "input_1", "text": "page", "merged": True},),
            trace=trace,
            trace_digest=canonical_trace_digest(trace),
        ),
        output={"text": "done"},
        exhausted=False,
    )

    page = session.recall_history(
        "session:turn/turn_exact_entry",
        max_entries=1,
        cursor={"entry_index": 1, "char_offset": 0},
    )

    assert page["requested_max_entries"] == 1
    assert page["effective_max_entries"] == 1
    assert page["returned_entry_indexes"] == [1]
    assert page["trace"] == [trace[1]]


def test_session_recall_never_returns_derived_background(tmp_path: Path) -> None:
    session = _engine(_settings(tmp_path))
    references = [f"workspace:doc/{index}-" + "x" * 120 for index in range(40)]
    output = to_json_object({"text": "answer", "references": references})
    _record_turn(
        session,
        summary=_summary("turn_large_background", ask="remember this"),
        output=output,
        exhausted=False,
    )

    page = session.recall_history(
        "session:turn/turn_large_background",
        max_chars=4000,
    )

    assert "background" not in page
    assert "background_state" not in page
    assert "preview" not in page
    assert len(dumps_json(page)) <= 4000


def test_session_root_inspect_cursor_is_bound_to_manifest_revision(
    tmp_path: Path,
) -> None:
    session = _engine(_settings(tmp_path))
    for index in range(2):
        _record_turn(
            session,
            summary=_summary(f"turn_revision_{index}", ask=f"ask {index}"),
            output={"text": f"answer {index}"},
            exhausted=False,
        )
    first = session.inspect_history(max_entries=1)
    next_cursor = first["next_cursor"]
    assert isinstance(next_cursor, dict)
    assert next_cursor["revision"] == session.revision

    _record_turn(
        session,
        summary=_summary("turn_revision_changed", ask="new ask"),
        output={"text": "new answer"},
        exhausted=False,
    )

    with pytest.raises(SessionHistoryRequestError) as failure:
        session.inspect_history(max_entries=1, cursor=next_cursor)
    assert failure.value.reason is SessionHistoryFailureReason.REVISION_CHANGED

    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
    result = SessionHistoryInspectExecutor(
        session,
        runtime_bridge=RuntimeSessionBridge(),
    ).execute(
        _history_execution(
            catalog,
            "session.history.inspect",
            {"max_entries": 1, "cursor": next_cursor},
        ),
        ActionExecutionContext(),
    )
    assert result.status is ActionResultStatus.FAILED
    assert result.failure is not None
    assert result.failure.reason == SessionHistoryFailureReason.REVISION_CHANGED.value
    assert result.failure.constraint == {"restart": "active_head"}
    assert result.failure.feedback == (
        "Session history changed; restart active-head inspection without a cursor."
    )


def test_session_root_cursor_binding_stays_inside_character_budget(
    tmp_path: Path,
) -> None:
    session = _engine(_settings(tmp_path))
    _record_turn(
        session,
        summary=_summary("turn_bound_revision", ask="x" * 2000),
        output={"text": "y" * 2000},
        exhausted=False,
    )

    page = session.inspect_history(max_chars=1024, max_entries=1)

    assert page["effective_max_chars"] == 1024
    assert len(dumps_json(page)) <= 1024
    cursor = page["cursor"]
    assert isinstance(cursor, dict)
    assert cursor["revision"] == session.revision
    next_cursor = page["next_cursor"]
    assert isinstance(next_cursor, dict)
    assert next_cursor["revision"] == session.revision


def test_session_overflow_background_recovers_through_root_inspect(
    tmp_path: Path,
) -> None:
    session = _engine(_settings(tmp_path, background_max_chars=512))
    _record_turn(
        session,
        summary=_summary("turn_overflow", ask="x" * 1200),
        output={"text": "y" * 1800},
        exhausted=False,
    )

    snapshot = session.background_snapshot(DAY)
    assert snapshot.items[0].content["kind"] == "session_overflow_head"
    before = snapshot
    inspected = session.inspect_history(max_chars=8000)
    items = inspected["items"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    assert item["ref"] == "session:turn/turn_overflow"
    preview = item["preview"]
    assert isinstance(preview, dict)
    assert preview["user_ask"] == ["x" * 1200]
    assert session.background_snapshot(DAY) == before


def test_session_record_turn_is_idempotent_for_identical_completion(
    tmp_path: Path,
) -> None:
    session = _engine(_settings(tmp_path))
    summary = _summary("turn_repeat", ask="same question")
    output: JsonObject = {"text": "same answer"}

    _record_turn(session, summary=summary, output=output, exhausted=False)
    revision = session.revision
    _record_turn(session, summary=summary, output=output, exhausted=False)

    assert session.revision == revision
    items = session.inspect_history()["items"]
    assert isinstance(items, list)
    assert len(items) == 1


def test_session_rejects_same_turn_ref_with_different_content(tmp_path: Path) -> None:
    session = _engine(_settings(tmp_path))
    _record_turn(
        session,
        summary=_summary("turn_conflict", ask="first"),
        output={"text": "answer"},
        exhausted=False,
    )

    with pytest.raises(SessionInvariantError, match="conflicts"):
        _record_turn(
            session,
            summary=_summary("turn_conflict", ask="different"),
            output={"text": "answer"},
            exhausted=False,
        )


def test_session_idempotency_ignores_changed_background_projection_settings(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    trace = (
        _decision_entry("reason_1", "core.reason", {"topic": "one"}),
        _result_entry("reason_1", "core.reason", {"text": "detail"}),
    )
    summary = replace(
        _summary("turn_projection", ask="same completion"),
        trace=trace,
        trace_digest=canonical_trace_digest(trace),
    )
    first = _engine(settings)
    _record_turn(
        first,
        summary=summary,
        output={"text": "same answer"},
        exhausted=False,
    )
    revision = first.revision

    restarted = _engine(
        replace(settings, background_action_names=())
    )
    _record_turn(
        restarted,
        summary=summary,
        output={"text": "same answer"},
        exhausted=False,
    )

    assert restarted.revision == revision
    snapshot = restarted.background_snapshot(DAY)
    assert snapshot.items[0].content["action_outcomes"] == [
        {
            "action": "core.reason",
            "success_count": 1,
            "failed_count": 0,
            "timeout_count": 0,
        }
    ]
    inspected = restarted.inspect_history("session:turn/turn_projection")["items"]
    assert isinstance(inspected, list) and isinstance(inspected[0], dict)
    preview = inspected[0]["preview"]
    assert isinstance(preview, dict)
    selected = preview["actions"]
    assert isinstance(selected, list) and len(selected) == 1
    selected_action = selected[0]
    assert isinstance(selected_action, dict)
    assert selected_action["action"] == "core.reason"


def test_session_reconciles_turn_orphan_after_manifest_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    store = SessionStore(root=settings.root)
    session = _engine(settings, store=store)
    original_save = store.save_manifest
    failed = False

    def fail_once(manifest) -> None:
        nonlocal failed
        if not failed and manifest.revision == 1:
            failed = True
            raise SessionIOError("injected manifest failure")
        original_save(manifest)

    monkeypatch.setattr(store, "save_manifest", fail_once)
    summary = _summary("turn_orphan", ask="recover me")

    with pytest.raises(SessionIOError, match="injected"):
        _record_turn(
            session,
            summary=summary,
            output={"text": "recovered"},
            exhausted=False,
        )

    recovered = _engine(settings)
    assert recovered.revision == 1
    assert recovered.last_reconcile_result.adopted_turn_refs == (
        "session:turn/turn_orphan",
    )
    _record_turn(
        recovered,
        summary=summary,
        output={"text": "recovered"},
        exhausted=False,
    )
    assert recovered.revision == 1


def test_history_queries_do_not_reconcile_an_uncommitted_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    store = SessionStore(root=settings.root)
    session = _engine(settings, store=store)
    original_save = store.save_manifest

    def fail_manifest(manifest) -> None:
        raise SessionIOError("injected manifest failure")

    monkeypatch.setattr(store, "save_manifest", fail_manifest)
    with pytest.raises(SessionIOError, match="injected"):
        _record_turn(
            session,
            summary=_summary("turn_pending", ask="pending question"),
            output={"text": "pending answer"},
            exhausted=False,
        )
    monkeypatch.setattr(store, "save_manifest", original_save)

    assert session.revision == 0
    assert session.inspect_history()["items"] == []
    assert session.inspect_history("session:turn/turn_pending")["items"]
    assert session.action_history("session:turn/turn_pending")["page_complete"] is True
    assert session.recall_history("session:turn/turn_pending")["page_complete"] is True
    assert session.revision == 0

    reconciled = session.reconcile_active()

    assert reconciled.adopted_turn_refs == ("session:turn/turn_pending",)
    assert session.revision == 1


def test_session_reuses_deterministic_summary_after_manifest_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path, background_max_chars=900)
    store = SessionStore(root=settings.root)
    session = _engine(settings, store=store)
    for index in range(2):
        _record_turn(
            session,
            summary=_summary(f"turn_{index}", ask=f"question {index}"),
            output={"text": "x" * 700},
            exhausted=False,
        )
    original_save = store.save_manifest

    def fail_revision_three(manifest) -> None:
        if manifest.revision == 3:
            raise SessionIOError("injected summary commit failure")
        original_save(manifest)

    monkeypatch.setattr(store, "save_manifest", fail_revision_three)
    with pytest.raises(SessionIOError, match="injected"):
        _record_turn(
            session,
            summary=_summary("turn_2", ask="question 2"),
            output={"text": "x" * 700},
            exhausted=False,
        )

    summary_files = tuple((settings.root / "summaries").glob("*.json"))
    assert len(summary_files) == 1
    recovered = _engine(settings)
    assert recovered.revision == 3
    assert len(tuple((settings.root / "summaries").glob("*.json"))) == 1


def test_session_rejects_corrupted_summary_background_on_reload(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, background_max_chars=900)
    session = _engine(settings)
    for index in range(3):
        _record_turn(
            session,
            summary=_summary(f"turn_corrupt_{index}", ask=f"question {index}"),
            output={"text": "answer " + "x" * 700},
            exhausted=False,
        )
    summary_files = tuple((settings.root / "summaries").glob("*.json"))
    assert len(summary_files) == 1
    summary_path = summary_files[0]
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    turns = persisted["content"]["background"]["turns"]
    turns[0]["answer"] = "fabricated summary answer"
    summary_path.write_text(
        json.dumps(persisted, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SessionInvariantError, match="background is inconsistent"):
        SessionEngine(settings)


def test_session_reconciles_orphans_before_explicit_archive(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    old_day = BusinessDay.parse("2026-07-11")
    store = SessionStore(root=settings.root)
    store.create_manifest(str(old_day))
    summary = _summary("turn_before_midnight", ask="persist before archive")
    action_history = project_turn_actions(
        summary.trace,
        expected_digest=summary.trace_digest,
    ).summary_json()
    store.save_record_if_absent(
        SessionRecord(
            ref="session:turn/turn_before_midnight",
            kind=SessionHistoryKind.TURN,
            content={
                "day": str(old_day),
                "background": {
                    "kind": "session_turn",
                    "ref": "session:turn/turn_before_midnight",
                    "turn_id": "turn_before_midnight",
                    "user_ask": ["persist before archive"],
                    "actions": [],
                    "answer": "archived answer",
                    "references": [],
                    "exhausted": False,
                    "action_outcome_summary": action_history["outcome"],
                    "trace_summary": summary.trace_summary,
                    "trace_digest": summary.trace_digest,
                },
                "completion": summary.to_json(),
                "action_history": action_history,
                "output": {"text": "archived answer"},
                "exhausted": False,
            },
        )
    )

    active = SessionEngine(settings)
    archive_target = tmp_path / "archive" / "stamp" / "session"
    active.archive_day(old_day, target=archive_target)
    archived_store = SessionStore(root=archive_target)
    archived = archived_store.load_manifest()

    assert active.active_day is None
    assert archived.revision == 1
    assert tuple(item.ref for item in archived.items) == (
        "session:turn/turn_before_midnight",
    )
    snapshot = active.archive_snapshot(old_day, root=archive_target)
    assert snapshot.day == old_day
    assert snapshot.root == archive_target.resolve()
    assert snapshot.revision == 1
    assert snapshot.has_facts is True
    assert tuple(item.ref for item in snapshot.items) == (
        "session:turn/turn_before_midnight",
    )

    with pytest.raises(SessionInvariantError, match="day mismatch"):
        active.archive_snapshot(DAY, root=archive_target)


def test_session_reports_persisted_manifest_shape_as_invariant_failure(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.root.mkdir(parents=True)
    (settings.root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 99,
                "day": str(DAY),
                "revision": 0,
                "items": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SessionInvariantError, match="manifest is invalid"):
        SessionEngine(settings)


def _settings(tmp_path: Path, *, background_max_chars: int = 24000) -> SessionSettings:
    return SessionSettings(
        root=tmp_path / "session",
        background_max_chars=background_max_chars,
        summary_watermark_ratio=0.60,
        summary_target_ratio=0.40,
        min_recent_turns=1,
        history_page_max_chars=8000,
    )


def _record_turn(
    session: SessionEngine,
    *,
    summary: TurnSummary,
    output: JsonObject | None,
    exhausted: bool,
) -> None:
    session.record_turn(
        summary=summary,
        output=output,
        exhausted=exhausted,
        day=DAY,
    )


def _engine(
    settings: SessionSettings,
    *,
    store: SessionStore | None = None,
) -> SessionEngine:
    engine = SessionEngine(settings, store=store)
    if engine.active_day is None:
        engine.initialize_day(DAY)
    elif engine.active_day != DAY:
        raise AssertionError("test Session has an unexpected active day")
    return engine


def _history_execution(
    catalog: ActionCatalog,
    action_name: str,
    params: JsonObject,
) -> ActionExecution:
    return ActionExecution(
        action=catalog.get_action(action_name),
        call=ActionCall(
            call_id=f"call_{action_name}",
            action_name=action_name,
            params=params,
            sequence=1,
        ),
        framework=ActionFramework(
            invoke_id=f"invoke_{action_name}",
            batch_id="batch_history",
            scope=RunScope(),
            domain="session",
        ),
    )


def _summary(turn_id: str, *, ask: str) -> TurnSummary:
    trace: tuple[JsonObject, ...] = (
        {
            "entry_id": f"entry_{turn_id}",
            "kind": "phase_note",
            "cycle_id": "cycle_1",
            "phase": "phase3",
            "message": {
                "role": "user",
                "label": "phase_note",
                "content": [{"type": "json", "value": {"note": "done"}}],
            },
            "origin_refs": [],
        },
    )
    return TurnSummary(
        turn_id=turn_id,
        inputs=(
            {
                "input_id": f"input_{turn_id}",
                "text": ask,
                "received_at": 1.0,
                "merged": True,
            },
        ),
        trace_summary={"entry_count": 1, "kinds": ["phase_note"]},
        trace_digest=canonical_trace_digest(trace),
        trace=trace,
    )


def _decision_entry(call_id: str, name: str, arguments: JsonObject) -> JsonObject:
    return {
        "entry_id": f"decision_{call_id}",
        "kind": "decision",
        "cycle_id": "cycle_1",
        "phase": "phase2",
        "message": {
            "role": "assistant",
            "label": "decision",
            "content": [],
            "tool_calls": [
                {"id": call_id, "name": name, "arguments": arguments, "kind": "action"},
            ],
        },
        "origin_refs": [],
    }


def _result_entry(call_id: str, name: str, result: JsonObject) -> JsonObject:
    return {
        "entry_id": f"result_{call_id}",
        "kind": "action_result",
        "cycle_id": "cycle_1",
        "phase": "phase3",
        "message": {
            "role": "tool_result",
            "label": "action_result",
            "call_id": call_id,
            "tool_name": name,
            "status": "ok",
            "content": [
                {
                    "type": "json",
                    "value": {
                        "action": name,
                        "status": "success",
                        "stage": "execute",
                        "payload": result,
                    },
                }
            ],
        },
        "origin_refs": [],
    }
