from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.action import (
    ActionCall,
    ActionExecution,
    ActionExecutionContext,
    ActionFramework,
    ActionResultStatus,
)
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.infra import JsonObject, JsonValue
from tinysoul.infra.time import BusinessDay
from tinysoul.runtime import RunScope
from tinysoul.runtime.bridge import RuntimeSessionBridge
from tinysoul.session import SessionEngine, SessionSettings
from tinysoul.session.actions import SessionInspectExecutor
from tinysoul.session.errors import (
    SessionInspectFailureReason,
    SessionInspectRequestError,
)
from tinysoul.session.models import (
    SessionOutputRecord,
    SessionSummaryRecord,
    summary_ref,
)
from tinysoul.session.store import SessionStore

from .synthetic import SyntheticAction, completion


DAY = BusinessDay.parse("2026-07-25")


def test_background_is_clean_and_inspect_expands_turn_actions(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.record_turn(
        completion(
            "turn_actions",
            ask="create a report",
            actions=(
                SyntheticAction(
                    "workspace.create",
                    request={"link": "workspace:report.md"},
                    result={"written": True},
                    references=("workspace:report.md",),
                ),
                SyntheticAction(
                    "web.search",
                    status=ActionResultStatus.FAILED,
                    result={"attempted": True},
                    failure_reason="provider_unavailable",
                ),
            ),
        ),
        day=DAY,
        output=SessionOutputRecord(
            text="report created",
            references=("workspace:report.md",),
        ),
        exhausted=False,
    )

    item = session.background_snapshot(DAY).items[0].content
    assert item == {
        "kind": "session_turn",
        "ref": "session:turn/turn_actions",
        "user_ask": ["create a report"],
        "answer": "report created",
        "references": ["workspace:report.md"],
        "actions": {
            "ref": "session:turn/turn_actions#actions",
            "count": 2,
            "outcomes": [
                {"action": "web.search", "counts": {"failed": 1}},
                {"action": "workspace.create", "counts": {"success": 1}},
            ],
        },
    }
    assert "trace" not in item
    assert "revision" not in item

    turn = session.inspect("session:turn/turn_actions")
    content = _json_object_list(turn["content"])
    turn_actions = _json_object(content[0]["actions"])
    turn_action_ref = turn_actions["ref"]
    assert isinstance(turn_action_ref, str)
    assert turn_action_ref.endswith("#actions")

    actions = session.inspect("session:turn/turn_actions#actions")
    headers = _json_object_list(actions["actions"])
    assert [header["outcome"] for header in headers] == ["success", "failed"]
    failure = _json_object(headers[1]["failure"])
    assert failure["reason"] == "provider_unavailable"
    assert headers[1]["result"] == {"attempted": True}

    leaf_ref = headers[0]["ref"]
    assert isinstance(leaf_ref, str)
    leaf = session.inspect(leaf_ref)
    detail = _json_object_list(leaf["content"])
    assert detail[0]["request"] == {"link": "workspace:report.md"}
    assert detail[0]["result"] == {"written": True}


def test_inspect_uses_opaque_continuation_for_oversized_content(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, inspect_max_chars=1024)
    session.record_turn(
        completion("turn_large", ask="q" * 3000),
        day=DAY,
        output=SessionOutputRecord(text="a" * 3000),
        exhausted=False,
    )

    first = session.inspect("session:turn/turn_large")
    token = first["next_continuation"]
    assert isinstance(token, str) and token.startswith("v1.")
    assert "content_fragment" in first
    assert "cursor" not in first
    second = session.inspect(
        "session:turn/turn_large",
        continuation=token,
    )
    fragment = _json_object(second["content_fragment"])
    assert fragment["text"]

    with pytest.raises(SessionInspectRequestError) as mismatch:
        session.inspect(None, continuation=token)
    assert mismatch.value.reason is SessionInspectFailureReason.INVALID_CONTINUATION


def test_summary_heap_keeps_recent_turn_and_expands_one_level(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, background_max_chars=512, min_recent_turns=1)
    for index in range(3):
        session.record_turn(
            completion(f"turn_{index}", ask=f"question {index}"),
            day=DAY,
            output=SessionOutputRecord(text="x" * 1000),
            exhausted=False,
        )

    root = session.inspect()
    nodes = _json_object_list(root["nodes"])
    assert [node["kind"] for node in nodes] == ["summary", "turn"]
    summary_ref = nodes[0]["ref"]
    assert isinstance(summary_ref, str)
    summary = session.inspect(summary_ref)
    children = _json_object_list(summary["nodes"])
    assert [child["ref"] for child in children] == [
        "session:turn/turn_0",
        "session:turn/turn_1",
    ]

    background = session.background_snapshot(DAY)
    assert background.items[0].content == {
        "kind": "session_overflow_head",
        "inspect_action": "core.session.inspect",
    }


def test_reconcile_adopts_an_uncommitted_turn_record(tmp_path: Path) -> None:
    session = _session(tmp_path)
    record = completion("turn_orphan")
    from tinysoul.session.completion import project_turn_record

    store = SessionStore(root=session.root)
    store.save_record_if_absent(
        project_turn_record(
            record,
            day=DAY,
            output=None,
            exhausted=True,
        )
    )

    result = session.reconcile_active()
    assert result.adopted_turn_refs == ("session:turn/turn_orphan",)
    nodes = _json_object_list(session.inspect()["nodes"])
    assert nodes[0]["ref"] == "session:turn/turn_orphan"


def test_inspect_rejects_record_outside_authoritative_graph(tmp_path: Path) -> None:
    session = _session(tmp_path)
    for turn_id in ("turn_root_1", "turn_root_2"):
        session.record_turn(
            completion(turn_id),
            day=DAY,
            output=None,
            exhausted=True,
        )
    children = (
        "session:turn/turn_root_1",
        "session:turn/turn_root_2",
    )
    orphan_ref = summary_ref(str(DAY), children)
    SessionStore(root=session.root).save_record_if_absent(
        SessionSummaryRecord(
            ref=orphan_ref,
            day=str(DAY),
            child_refs=children,
        )
    )

    with pytest.raises(SessionInspectRequestError) as raised:
        session.inspect(orphan_ref)

    assert raised.value.reason is SessionInspectFailureReason.UNKNOWN_REF


def test_session_inspect_executor_returns_foldable_origin(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, inspect_max_chars=1024)
    session.record_turn(
        completion("turn_executor", ask="q" * 3000),
        day=DAY,
        output=None,
        exhausted=True,
    )
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))
    action = catalog.get_action("core.session.inspect")
    execution = ActionExecution(
        action=action,
        call=ActionCall(
            call_id="call_inspect",
            action_name=action.name,
            params={"ref": "session:turn/turn_executor"},
            sequence=1,
        ),
        framework=ActionFramework(
            invoke_id="invoke_inspect",
            batch_id="batch_inspect",
            scope=RunScope(),
            domain="core",
        ),
    )
    result = SessionInspectExecutor(
        session,
        runtime_bridge=RuntimeSessionBridge(),
    ).execute(execution, ActionExecutionContext())
    assert result.status is ActionResultStatus.SUCCESS
    assert result.trace_projection is not None
    assert result.trace_projection.origin_refs == (
        "session:turn/turn_executor",
    )
    assert "next_continuation" in result.payload
    assert "next_continuation" not in result.trace_projection.canonical_payload


def test_archive_snapshot_contains_only_validated_roots(tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.record_turn(
        completion("turn_archive"),
        day=DAY,
        output=SessionOutputRecord(text="done"),
        exhausted=False,
    )
    archive = (tmp_path / "archive" / "session").resolve()
    session.archive_day(DAY, target=archive)
    snapshot = session.archive_snapshot(DAY, root=archive)
    assert snapshot.refs == ("session:turn/turn_archive",)
    assert snapshot.has_facts


def _session(
    tmp_path: Path,
    *,
    background_max_chars: int = 24000,
    min_recent_turns: int = 2,
    inspect_max_chars: int = 8000,
) -> SessionEngine:
    session = SessionEngine(
        SessionSettings(
            root=tmp_path / "runtime" / "session",
            background_max_chars=background_max_chars,
            summary_watermark_ratio=0.60,
            summary_target_ratio=0.40,
            min_recent_turns=min_recent_turns,
            inspect_max_chars=inspect_max_chars,
        )
    )
    session.initialize_day(DAY)
    return session


def _json_object(value: JsonValue) -> JsonObject:
    assert isinstance(value, dict)
    return value


def _json_object_list(value: JsonValue) -> list[JsonObject]:
    assert isinstance(value, list)
    return [_json_object(item) for item in value]
