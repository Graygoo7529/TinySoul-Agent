"""Session persistence, summarization, and Turn projection tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tinysoul.context import ContextEngineBuilder, ContextSignalBatch, TurnSummary
from tinysoul.context.prompts import PromptBlock, TaskPrompt
from tinysoul.infra.json import JsonObject
from tinysoul.loop import TurnPreparationRequest
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.session import SessionEngine, SessionSettings
from tinysoul.session.projection import SessionTurnPreparationHandler


def test_session_persists_turns_and_builds_hierarchical_summary(tmp_path: Path) -> None:
    settings = _settings(tmp_path, background_max_chars=900)
    session = SessionEngine(settings)

    for index in range(3):
        session.record_turn(
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

    reloaded = SessionEngine(settings)
    assert reloaded.revision == session.revision
    assert reloaded.inspect_history()["items"] == items


def test_session_background_is_prepared_before_home_background(tmp_path: Path) -> None:
    session = SessionEngine(_settings(tmp_path))
    session.record_turn(
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
    scope = RunScope().push(RunLevel.PROGRAM, "program").push(RunLevel.TURN, turn_id)
    request = TurnPreparationRequest(
        turn_id=turn_id,
        user_input="current question",
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
    session = SessionEngine(_settings(tmp_path))
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

    session.record_turn(summary=summary, output={"text": "done"}, exhausted=False)

    snapshot = session.background_snapshot()
    actions = snapshot.items[0].content["actions"]
    assert isinstance(actions, list)
    assert len(actions) == 1
    action = actions[0]
    assert isinstance(action, dict)
    assert action["action"] == "core.reason"
    assert action["result"]


def test_session_turn_recall_uses_bounded_continuation_cursor(tmp_path: Path) -> None:
    settings = replace(_settings(tmp_path), recall_max_chars=350)
    session = SessionEngine(settings)
    trace: tuple[JsonObject, ...] = tuple(
        {"entry_id": f"entry_{index}", "detail": "x" * 180}
        for index in range(3)
    )
    session.record_turn(
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


def _settings(tmp_path: Path, *, background_max_chars: int = 24000) -> SessionSettings:
    return SessionSettings(
        root=tmp_path / "session",
        archive_root=tmp_path / "archive",
        background_max_chars=background_max_chars,
        summary_watermark_ratio=0.60,
        summary_target_ratio=0.40,
        min_recent_turns=1,
        recall_max_chars=8000,
    )


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
