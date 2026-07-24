from __future__ import annotations

from dataclasses import replace

import pytest

from tinysoul.context import TurnSummary, canonical_trace_digest
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.session import SessionInvariantError, project_turn_actions
from tinysoul.session.models import SessionHistoryKind, SessionRecord
from tinysoul.session.validation import validate_turn_record


def test_turn_record_validator_accepts_consistent_derived_facts() -> None:
    record = _turn_record()

    validated = validate_turn_record(record)

    assert validated.turn_id == "turn_valid"
    assert validated.trace_digest == canonical_trace_digest(validated.trace)
    assert validated.action_projection.summary_json() == record.content["action_history"]


def test_turn_record_validator_rejects_trace_digest_mismatch() -> None:
    record = _turn_record()
    completion = _completion(record)
    completion["trace"] = [
        {
            "entry_id": "changed",
            "kind": "phase_note",
            "cycle_id": "cycle_1",
            "phase": "phase3",
            "message": {
                "role": "user",
                "label": "phase_note",
                "content": [],
            },
            "origin_refs": [],
        }
    ]
    changed = replace(record, content={**record.content, "completion": completion})

    with pytest.raises(SessionInvariantError, match="trace digest"):
        validate_turn_record(changed)


def test_turn_record_validator_rejects_stale_action_projection() -> None:
    record = _turn_record()
    completion = _completion(record)
    changed = replace(
        record,
        content={
            **record.content,
            "action_history": {
                "trace_digest": completion["trace_digest"],
                "outcome": {"scan_complete": False},
                "by_action": [],
                "failure_groups": [],
            },
        },
    )

    with pytest.raises(SessionInvariantError, match="Action history"):
        validate_turn_record(changed)


def _turn_record() -> SessionRecord:
    trace: tuple[JsonObject, ...] = ()
    digest = canonical_trace_digest(trace)
    summary = TurnSummary(
        turn_id="turn_valid",
        inputs=({"input_id": "input_1", "text": "question", "merged": True},),
        trace_summary={"entry_count": 0},
        trace_digest=digest,
        trace=trace,
    )
    projection = project_turn_actions(trace, expected_digest=digest)
    return SessionRecord(
        ref="session:turn/turn_valid",
        kind=SessionHistoryKind.TURN,
        content={
            "day": "2026-07-24",
            "background": {
                "kind": "session_turn",
                "ref": "session:turn/turn_valid",
                "turn_id": "turn_valid",
                "user_ask": ["question"],
                "actions": [],
                "answer": "",
                "references": [],
                "exhausted": False,
                "action_outcome_summary": projection.outcome_summary(),
                "trace_summary": summary.trace_summary,
                "trace_digest": digest,
            },
            "completion": summary.to_json(),
            "action_history": projection.summary_json(),
            "output": None,
            "exhausted": False,
        },
    )


def _completion(record: SessionRecord) -> JsonObject:
    value = record.content.get("completion")
    assert isinstance(value, dict)
    return to_json_object(value)
