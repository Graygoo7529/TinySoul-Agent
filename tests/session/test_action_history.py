from __future__ import annotations

from tinysoul.action import (
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResultEnvelope,
    ActionResultStage,
    ActionResultStatus,
)
from tinysoul.context import canonical_trace_digest
from tinysoul.infra.json import JsonObject
from tinysoul.session import project_turn_actions


def test_action_history_aggregates_statuses_and_repeated_failures() -> None:
    failure = ActionLocalFailure(
        reason="request_rejected",
        scope="test.operation",
        disposition=ActionFailureDisposition.CHANGE_REQUEST,
        feedback="Change the request.",
        constraint={"field": "value"},
    )
    trace = (
        _call("call_success", "test.alpha"),
        _result("call_success", "test.alpha", ActionResultStatus.SUCCESS),
        _call("call_failed_1", "test.beta"),
        _result("call_failed_1", "test.beta", ActionResultStatus.FAILED, failure),
        _call("call_failed_2", "test.beta"),
        _result("call_failed_2", "test.beta", ActionResultStatus.FAILED, failure),
        _call("call_timeout", "test.alpha"),
        _result("call_timeout", "test.alpha", ActionResultStatus.TIMEOUT, failure),
    )

    projection = project_turn_actions(
        trace,
        expected_digest=canonical_trace_digest(trace),
    )

    assert projection.outcome_summary() == {
        "call_count": 4,
        "result_count": 4,
        "success_count": 1,
        "failed_count": 2,
        "timeout_count": 1,
        "unmatched_call_count": 0,
        "unmatched_result_count": 0,
        "pairing_issue_count": 0,
        "scan_complete": True,
        "pairing_complete": True,
    }
    by_action = {item["action"]: item for item in projection.by_action()}
    assert by_action["test.alpha"]["success"] == 1
    assert by_action["test.alpha"]["timeout"] == 1
    assert by_action["test.beta"]["failed"] == 2
    assert projection.background_outcomes() == (
        {
            "action": "test.alpha",
            "success_count": 1,
            "failed_count": 0,
            "timeout_count": 1,
        },
        {
            "action": "test.beta",
            "success_count": 0,
            "failed_count": 2,
            "timeout_count": 0,
        },
    )
    failure_groups = projection.failure_groups()
    assert [group["count"] for group in failure_groups] == [1, 2]
    assert {group["reason"] for group in failure_groups} == {"request_rejected"}


def _call(call_id: str, action_name: str) -> JsonObject:
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


def _result(
    call_id: str,
    action_name: str,
    status: ActionResultStatus,
    failure: ActionLocalFailure | None = None,
) -> JsonObject:
    stage = (
        ActionResultStage.EXECUTE
        if status is not ActionResultStatus.TIMEOUT
        else ActionResultStage.TIMEOUT
    )
    envelope = ActionResultEnvelope(
        action_name=action_name,
        status=status,
        stage=stage,
        failure=failure,
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
            "status": "ok" if status is ActionResultStatus.SUCCESS else "error",
            "content": [{"type": "json", "value": envelope.to_json()}],
        },
        "origin_refs": [],
    }
