"""Session persistence, summarization, and Turn projection tests."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tinysoul.context import ContextEngineBuilder, ContextSignalBatch, TurnSummary
from tinysoul.context.prompts import PromptBlock, TaskPrompt
from tinysoul.infra.json import JsonObject
from tinysoul.loop import BusinessDay, TurnPreparationRequest
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.session import (
    SessionEngine,
    SessionIOError,
    SessionInvariantError,
    SessionSettings,
)
from tinysoul.session.store import SessionStore
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
    child_refs = summary_header["child_refs"]
    assert child_refs == ["session:turn/turn_0", "session:turn/turn_1"]

    summary_ref = summary_header["ref"]
    assert isinstance(summary_ref, str)
    recalled_summary = session.recall_history(summary_ref)
    content = recalled_summary["content"]
    assert isinstance(content, dict)
    assert content["child_refs"] == child_refs
    recalled_turn = session.recall_history("session:turn/turn_0", max_chars=700)
    assert recalled_turn["ref"] == "session:turn/turn_0"

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
        .add_default_background("home:agent@core", "agent home")
        .build()
    )
    turn_id = context.begin_turn("current question")
    context.prepare_default_background()
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
        "background:home:agent@core"
    )
    late_results = context.consume_signal_batch(
        ContextSignalBatch(turn_id=turn_id, signals=signals)
    )
    assert len(late_results) == 1
    assert "preparation" in late_results[0].model_feedback


def test_session_projects_only_policy_selected_action_history(tmp_path: Path) -> None:
    session = _engine(_settings(tmp_path))
    summary = TurnSummary(
        turn_id="turn_actions",
        inputs=({"input_id": "input_1", "text": "analyze", "merged": True},),
        trace=(
            _decision_entry("call_reason", "core.reason", {"topic": "design"}),
            _decision_entry("call_scan", "workspace.scan", {}),
            _result_entry("call_reason", "core.reason", {"conclusion": "keep it"}),
            _result_entry("call_scan", "workspace.scan", {"count": 2}),
        ),
    )

    _record_turn(session, summary=summary, output={"text": "done"}, exhausted=False)

    snapshot = session.background_snapshot(DAY)
    actions = snapshot.items[0].content["actions"]
    assert isinstance(actions, list)
    assert len(actions) == 1
    action = actions[0]
    assert isinstance(action, dict)
    assert action["action"] == "core.reason"
    assert action["result"]


def test_session_turn_recall_uses_bounded_continuation_cursor(tmp_path: Path) -> None:
    settings = replace(_settings(tmp_path), recall_max_chars=350)
    session = _engine(settings)
    trace: tuple[JsonObject, ...] = tuple(
        {"entry_id": f"entry_{index}", "detail": "x" * 180}
        for index in range(3)
    )
    _record_turn(
        session,
        summary=TurnSummary(
            turn_id="turn_paged",
            inputs=({"input_id": "input_1", "text": "page", "merged": True},),
            trace=trace,
        ),
        output={"text": "done"},
        exhausted=False,
    )

    first = session.recall_history(
        "session:turn/turn_paged",
        max_chars=10000,
    )
    assert first["next_cursor"] == 1
    second = session.recall_history(
        "session:turn/turn_paged",
        cursor=1,
    )
    assert second["cursor"] == 1
    assert second["next_cursor"] == 2


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
    summary = replace(
        _summary("turn_projection", ask="same completion"),
        trace=(
            _decision_entry("reason_1", "core.reason", {"topic": "one"}),
            _result_entry("reason_1", "core.reason", {"text": "detail"}),
        ),
        trace_digest={"entry_count": 2},
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


def test_session_reconciles_orphans_before_explicit_archive(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    old_day = BusinessDay.parse("2026-07-11")
    store = SessionStore(root=settings.root)
    store.create_manifest(str(old_day))
    summary = _summary("turn_before_midnight", ask="persist before archive")
    store.save_record_if_absent(
        SessionRecord(
            ref="session:turn/turn_before_midnight",
            kind=SessionHistoryKind.TURN,
            content={
                "day": str(old_day),
                "background": {
                    "kind": "session_turn",
                    "turn_id": "turn_before_midnight",
                },
                "completion": summary.to_json(),
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
        recall_max_chars=8000,
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


def _summary(turn_id: str, *, ask: str) -> TurnSummary:
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
        trace_digest={"entry_count": 1},
        trace=(
            {
                "entry_id": f"entry_{turn_id}",
                "kind": "phase_note",
                "content": {"note": "done"},
            },
        ),
    )


def _decision_entry(call_id: str, name: str, arguments: JsonObject) -> JsonObject:
    return {
        "entry_id": f"decision_{call_id}",
        "kind": "decision",
        "message": {
            "role": "assistant",
            "tool_calls": [
                {"id": call_id, "name": name, "arguments": arguments},
            ],
        },
    }


def _result_entry(call_id: str, name: str, result: JsonObject) -> JsonObject:
    return {
        "entry_id": f"result_{call_id}",
        "kind": "action_result",
        "message": {
            "role": "tool_result",
            "call_id": call_id,
            "tool_name": name,
            "status": "ok",
            "content": [{"type": "json", "value": result}],
        },
    }
