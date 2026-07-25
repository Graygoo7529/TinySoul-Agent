from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tinysoul.session.errors import SessionContractError, SessionInvariantError
from tinysoul.session.models import (
    SESSION_MANIFEST_SCHEMA_VERSION,
    SESSION_RECORD_SCHEMA_VERSION,
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
