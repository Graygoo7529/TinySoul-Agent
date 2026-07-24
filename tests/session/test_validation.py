from __future__ import annotations

from dataclasses import replace

import pytest

from tinysoul.action import (
    ActionResultEnvelope,
    ActionResultStage,
    ActionResultStatus,
)
from tinysoul.context import TurnSummary, canonical_trace_digest
from tinysoul.infra.json import JsonObject, JsonValue, dumps_json, to_json_object
from tinysoul.session import SessionInvariantError, project_turn_actions
from tinysoul.session.background import (
    project_summary_background,
    project_turn_background,
    select_turn_background_actions,
    summary_ref,
)
from tinysoul.session.models import (
    SessionHistoryItem,
    SessionHistoryKind,
    SessionRecord,
)
from tinysoul.session.validation import (
    validate_summary_record,
    validate_turn_record,
)


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


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("user_ask", ["different question"]),
        ("answer", "different answer"),
        ("references", ["workspace:different.md"]),
    ),
)
def test_turn_record_validator_rejects_background_source_fact_drift(
    field: str,
    value: JsonValue,
) -> None:
    record = _turn_record(
        output={
            "text": "answer",
            "references": ["workspace:source.md"],
        }
    )
    background = _background(record)
    background[field] = value
    changed = replace(
        record,
        content={**record.content, "background": background},
    )

    with pytest.raises(SessionInvariantError, match="source facts"):
        validate_turn_record(changed)


def test_turn_record_validator_accepts_historical_action_selection() -> None:
    trace = (
        _action_call("call_1", "test.alpha"),
        _action_result("call_1", "test.alpha"),
        _action_call("call_2", "test.beta"),
        _action_result("call_2", "test.beta"),
    )
    record = _turn_record(
        trace=trace,
        action_names=frozenset({"test.beta"}),
    )

    validated = validate_turn_record(record)

    assert [item["action"] for item in validated.background_actions] == [
        "test.beta"
    ]


def test_turn_record_validator_rejects_fabricated_background_action() -> None:
    trace = (
        _action_call("call_1", "test.alpha"),
        _action_result("call_1", "test.alpha"),
    )
    record = _turn_record(
        trace=trace,
        action_names=frozenset({"test.alpha"}),
    )
    background = _background(record)
    actions = background["actions"]
    assert isinstance(actions, list) and isinstance(actions[0], dict)
    actions[0]["action"] = "test.fabricated"

    with pytest.raises(SessionInvariantError, match="background action"):
        validate_turn_record(
            replace(record, content={**record.content, "background": background})
        )


def test_summary_record_validator_rejects_background_drift() -> None:
    record = _summary_record()
    background = _background(record)
    turns = background["turns"]
    assert isinstance(turns, list) and isinstance(turns[0], dict)
    turns[0]["answer"] = "fabricated summary answer"

    with pytest.raises(SessionInvariantError, match="background"):
        validate_summary_record(
            replace(record, content={**record.content, "background": background})
        )


def test_summary_record_validator_rejects_nondeterministic_identity() -> None:
    record = _summary_record()

    with pytest.raises(SessionInvariantError, match="identity"):
        validate_summary_record(replace(record, ref="session:summary/summary_invalid"))


def _turn_record(
    *,
    turn_id: str = "turn_valid",
    output: JsonObject | None = None,
    trace: tuple[JsonObject, ...] = (),
    action_names: frozenset[str] = frozenset(),
) -> SessionRecord:
    digest = canonical_trace_digest(trace)
    summary = TurnSummary(
        turn_id=turn_id,
        inputs=({"input_id": "input_1", "text": "question", "merged": True},),
        trace_summary={"entry_count": 0},
        trace_digest=digest,
        trace=trace,
    )
    projection = project_turn_actions(trace, expected_digest=digest)
    ref = f"session:turn/{turn_id}"
    actions = select_turn_background_actions(
        projection,
        action_names=action_names,
        max_actions=3,
    )
    return SessionRecord(
        ref=ref,
        kind=SessionHistoryKind.TURN,
        content={
            "day": "2026-07-24",
            "background": project_turn_background(
                ref=ref,
                turn_id=turn_id,
                inputs=summary.inputs,
                output=output,
                exhausted=False,
                trace_summary=summary.trace_summary,
                trace_digest=digest,
                action_outcome_summary=projection.outcome_summary(),
                actions=actions,
            ),
            "completion": summary.to_json(),
            "action_history": projection.summary_json(),
            "output": output,
            "exhausted": False,
        },
    )


def _summary_record() -> SessionRecord:
    children = tuple(_history_item(_turn_record(turn_id=f"turn_{index}")) for index in range(2))
    child_refs = tuple(child.ref for child in children)
    ref = summary_ref("2026-07-24", child_refs)
    return SessionRecord(
        ref=ref,
        kind=SessionHistoryKind.SUMMARY,
        content={
            "day": "2026-07-24",
            "background": project_summary_background(ref, children),
            "child_refs": list(child_refs),
            "children": [child.to_json() for child in children],
        },
    )


def _history_item(record: SessionRecord) -> SessionHistoryItem:
    background = _background(record)
    turn_id = record.ref.rsplit("/", 1)[1]
    return SessionHistoryItem(
        item_id=turn_id,
        ref=record.ref,
        kind=SessionHistoryKind.TURN,
        background=background,
        char_count=len(dumps_json(background)),
    )


def _background(record: SessionRecord) -> JsonObject:
    value = record.content.get("background")
    assert isinstance(value, dict)
    return to_json_object(value)


def _completion(record: SessionRecord) -> JsonObject:
    value = record.content.get("completion")
    assert isinstance(value, dict)
    return to_json_object(value)


def _action_call(call_id: str, action_name: str) -> JsonObject:
    return {
        "entry_id": f"decision_{call_id}",
        "kind": "decision",
        "cycle_id": "cycle_test",
        "phase": "phase2",
        "message": {
            "role": "assistant",
            "label": "decision",
            "content": [],
            "tool_calls": [
                {
                    "id": call_id,
                    "name": action_name,
                    "arguments": {},
                    "kind": "action",
                }
            ],
        },
        "origin_refs": [],
    }


def _action_result(call_id: str, action_name: str) -> JsonObject:
    envelope = ActionResultEnvelope(
        action_name=action_name,
        status=ActionResultStatus.SUCCESS,
        stage=ActionResultStage.EXECUTE,
    )
    return {
        "entry_id": f"result_{call_id}",
        "kind": "action_result",
        "cycle_id": "cycle_test",
        "phase": "phase3",
        "message": {
            "role": "tool_result",
            "label": "action_result",
            "call_id": call_id,
            "tool_name": action_name,
            "status": "ok",
            "content": [{"type": "json", "value": envelope.to_json()}],
        },
        "origin_refs": [],
    }
