from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from tinysoul.action import (
    ActionFailureDisposition,
    ActionLocalFailure,
)
from tinysoul.session.errors import SessionContractError, SessionInvariantError
from tinysoul.session.models import (
    SESSION_MANIFEST_SCHEMA_VERSION,
    SESSION_RECORD_SCHEMA_VERSION,
    SessionActionOutcome,
    SessionActionRecord,
    SessionInputRecord,
    SessionManifest,
    SessionSummaryRecord,
    SessionTurnRecord,
    session_record_from_json,
    summary_ref,
)
from tinysoul.session.store import SessionStore
from tinysoul.session.validation import validate_summary_record


DAY = "2026-07-25"


def test_v4_turn_record_round_trips_and_rejects_unknown_fields() -> None:
    record = _turn("turn_roundtrip")
    assert SESSION_RECORD_SCHEMA_VERSION == 4
    assert session_record_from_json(record.to_json()) == record

    invalid = {**record.to_json(), "trace": []}
    with pytest.raises(SessionContractError, match="fields"):
        session_record_from_json(invalid)


def test_session_action_failure_is_typed_and_round_trips() -> None:
    failure = _failure()
    record = SessionActionRecord(
        action="workspace.create",
        request={"target_link": "workspace:report.md"},
        outcome=SessionActionOutcome.FAILED,
        failure=failure,
    )

    restored = SessionActionRecord.from_json(record.to_json())

    assert restored == record
    assert restored.failure is not None
    assert restored.failure.to_json() == failure.to_json()


@pytest.mark.parametrize(
    "failure",
    [
        {},
        {"arbitrary": True},
        {
            "reason": "write_failed",
            "scope": "workspace.action",
            "disposition": "unknown",
            "feedback": "Write failed.",
        },
        {
            "reason": "write_failed",
            "scope": "workspace.action",
            "disposition": "change_request",
            "feedback": "Write failed.",
            "unknown": True,
        },
    ],
)
def test_session_action_rejects_invalid_persisted_failure(failure: object) -> None:
    with pytest.raises(SessionContractError, match="failure is invalid"):
        SessionActionRecord.from_json(
            {
                "action": "workspace.create",
                "request": {},
                "outcome": "failed",
                "failure": failure,
            }
        )


def test_session_action_requires_typed_failure_and_reserved_result_boundary() -> None:
    with pytest.raises(SessionContractError, match="must be an ActionLocalFailure"):
        SessionActionRecord(
            action="workspace.create",
            request={},
            outcome=SessionActionOutcome.FAILED,
            failure=cast(ActionLocalFailure, _failure().to_json()),
        )

    with pytest.raises(SessionContractError, match="result cannot contain failure"):
        SessionActionRecord(
            action="workspace.create",
            request={},
            outcome=SessionActionOutcome.SUCCESS,
            result={"failure": _failure().to_json()},
        )


def test_store_rejects_malformed_persisted_action_failure(tmp_path: Path) -> None:
    store = SessionStore(root=tmp_path / "session")
    store.create_manifest(DAY)
    raw = _turn("turn_invalid_failure").to_json()
    raw["actions"] = [
        {
            "action": "workspace.create",
            "request": {},
            "outcome": "failed",
            "failure": {"arbitrary": True},
        }
    ]
    path = store.root / "turns" / "turn_invalid_failure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SessionInvariantError, match="failure is invalid"):
        store.load_record("session:turn/turn_invalid_failure")


def test_manifest_v2_is_only_an_ordered_root_set() -> None:
    manifest = SessionManifest(day=DAY, revision=2, refs=("session:turn/turn_a",))
    assert SESSION_MANIFEST_SCHEMA_VERSION == 2
    assert manifest.to_json() == {
        "schema_version": 2,
        "day": DAY,
        "revision": 2,
        "refs": ["session:turn/turn_a"],
    }


def test_summary_identity_is_derived_from_direct_children() -> None:
    children = ("session:turn/turn_a", "session:turn/turn_b")
    record = SessionSummaryRecord(
        ref=summary_ref(DAY, children),
        day=DAY,
        child_refs=children,
    )
    assert validate_summary_record(record) is record

    with pytest.raises(SessionInvariantError, match="identity"):
        validate_summary_record(replace(record, ref="session:summary/summary_wrong"))


def test_store_reuses_equal_facts_and_rejects_conflicts(tmp_path: Path) -> None:
    store = SessionStore(root=tmp_path / "session")
    store.create_manifest(DAY)
    first = _turn("turn_immutable")
    stored = store.save_record_if_absent(first)
    assert store.save_record_if_absent(replace(first, recorded_at_ns=99)) == stored

    with pytest.raises(SessionInvariantError, match="conflicts"):
        store.save_record_if_absent(replace(first, working={"changed": True}))


def _turn(turn_id: str) -> SessionTurnRecord:
    return SessionTurnRecord(
        ref=f"session:turn/{turn_id}",
        day=DAY,
        inputs=(SessionInputRecord(text="question", received_at=1.0),),
        working={},
        background_links=(),
        output=None,
        exhausted=False,
        actions=(),
        recorded_at_ns=1,
    )


def _failure() -> ActionLocalFailure:
    return ActionLocalFailure(
        reason="write_failed",
        scope="workspace.action",
        disposition=ActionFailureDisposition.CHANGE_REQUEST,
        feedback="Write failed.",
        constraint={"target_link": "workspace:report.md"},
    )
