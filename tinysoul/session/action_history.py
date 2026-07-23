"""Deterministic Action history projected from an immutable Turn trace."""

from __future__ import annotations

from collections.abc import Mapping
from collections import defaultdict
from dataclasses import dataclass, field, replace
from enum import StrEnum

from tinysoul.action import ActionResultEnvelope, ActionResultStatus
from tinysoul.action.core.errors import ActionInvariantError
from tinysoul.context import canonical_trace_digest
from tinysoul.infra.json import JsonObject, to_json_object

from .errors import SessionContractError, SessionInvariantError


class ActionPairingIssue(StrEnum):
    """Stable kinds of non-bijective Action call/result pairing."""

    MISSING_RESULT = "missing_result"
    ORPHAN_RESULT = "orphan_result"
    DUPLICATE_CALL_ID = "duplicate_call_id"
    DUPLICATE_RESULT = "duplicate_result"
    NAME_MISMATCH = "name_mismatch"


@dataclass(frozen=True)
class TurnActionDetail:
    """One ordered call or orphan result occurrence without raw business data."""

    occurrence: int
    call_id: str
    action_name: str
    call_trace_index: int | None = None
    result_trace_index: int | None = None
    cycle_id: str = ""
    phase: str = ""
    status: ActionResultStatus | None = None
    stage: str = ""
    failure: JsonObject | None = None
    pairing_issue: ActionPairingIssue | None = None

    def __post_init__(self) -> None:
        if self.occurrence < 0:
            raise SessionContractError("Action occurrence cannot be negative")
        if not self.call_id or not self.action_name:
            raise SessionContractError("Action detail identity must be non-empty")
        for index in (self.call_trace_index, self.result_trace_index):
            if index is not None and (isinstance(index, bool) or index < 0):
                raise SessionContractError("Action trace index cannot be negative")
        if self.failure is not None:
            object.__setattr__(self, "failure", to_json_object(self.failure))

    def to_json(self) -> JsonObject:
        value: JsonObject = {
            "occurrence": self.occurrence,
            "call_id": self.call_id,
            "action": self.action_name,
            "call_trace_index": self.call_trace_index,
            "result_trace_index": self.result_trace_index,
            "cycle_id": self.cycle_id,
            "phase": self.phase,
        }
        if self.status is not None:
            value["status"] = self.status.value
        if self.stage:
            value["stage"] = self.stage
        if self.failure is not None:
            value["failure"] = self.failure
        if self.pairing_issue is not None:
            value["pairing_issue"] = self.pairing_issue.value
        return value


@dataclass(frozen=True)
class TurnActionProjection:
    """Complete deterministic Action facts for one canonical Turn trace."""

    trace_digest: str
    details: tuple[TurnActionDetail, ...] = field(default_factory=tuple)
    call_count: int = 0
    result_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", tuple(self.details))

    @property
    def success_count(self) -> int:
        return sum(item.status is ActionResultStatus.SUCCESS for item in self.details)

    @property
    def failed_count(self) -> int:
        return sum(item.status is ActionResultStatus.FAILED for item in self.details)

    @property
    def timeout_count(self) -> int:
        return sum(item.status is ActionResultStatus.TIMEOUT for item in self.details)

    @property
    def pairing_issue_count(self) -> int:
        return sum(item.pairing_issue is not None for item in self.details)

    @property
    def unmatched_call_count(self) -> int:
        return sum(
            item.call_trace_index is not None and item.pairing_issue is not None
            for item in self.details
        )

    @property
    def unmatched_result_count(self) -> int:
        return sum(
            item.result_trace_index is not None and item.pairing_issue is not None
            for item in self.details
        )

    def outcome_summary(self) -> JsonObject:
        return {
            "call_count": self.call_count,
            "result_count": self.result_count,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "timeout_count": self.timeout_count,
            "unmatched_call_count": self.unmatched_call_count,
            "unmatched_result_count": self.unmatched_result_count,
            "pairing_issue_count": self.pairing_issue_count,
            "scan_complete": True,
            "pairing_complete": self.pairing_issue_count == 0,
        }

    def by_action(self) -> tuple[JsonObject, ...]:
        counters: dict[str, dict[str, int]] = defaultdict(
            lambda: {"calls": 0, "results": 0, "success": 0, "failed": 0, "timeout": 0}
        )
        for item in self.details:
            counter = counters[item.action_name]
            if item.call_trace_index is not None:
                counter["calls"] += 1
            if item.result_trace_index is not None:
                counter["results"] += 1
            if item.status is not None:
                counter[item.status.value] += 1
        return tuple(
            to_json_object({"action": name, **counters[name]})
            for name in sorted(counters)
        )

    def failure_groups(self) -> tuple[JsonObject, ...]:
        counters: dict[tuple[str, str, str, str], int] = defaultdict(int)
        feedback: dict[tuple[str, str, str, str], tuple[str, JsonObject]] = {}
        for item in self.details:
            failure = item.failure
            if failure is None:
                continue
            reason = _required_text(failure, "reason", owner="Action failure")
            disposition = _required_text(
                failure, "disposition", owner="Action failure"
            )
            key = (item.action_name, reason, item.stage, disposition)
            counters[key] += 1
            constraint = failure.get("constraint", {})
            feedback[key] = (
                _required_text(failure, "feedback", owner="Action failure"),
                to_json_object(constraint) if isinstance(constraint, dict) else {},
            )
        return tuple(
            to_json_object(
                {
                    "action": key[0],
                    "reason": key[1],
                    "stage": key[2],
                    "disposition": key[3],
                    "count": counters[key],
                    "feedback": feedback[key][0],
                    "constraint": feedback[key][1],
                }
            )
            for key in sorted(counters)
        )

    def summary_json(self) -> JsonObject:
        return {
            "trace_digest": self.trace_digest,
            "outcome": self.outcome_summary(),
            "by_action": list(self.by_action()),
            "failure_groups": list(self.failure_groups()),
        }


@dataclass(frozen=True)
class _CallOccurrence:
    call_id: str
    action_name: str
    trace_index: int
    cycle_id: str
    phase: str


@dataclass(frozen=True)
class _ResultOccurrence:
    call_id: str
    action_name: str
    trace_index: int
    cycle_id: str
    phase: str
    envelope: ActionResultEnvelope


def project_turn_actions(
    trace: tuple[JsonObject, ...],
    *,
    expected_digest: str,
) -> TurnActionProjection:
    """Validate and project every Action call/result occurrence in one Turn."""

    actual_digest = canonical_trace_digest(trace)
    if actual_digest != expected_digest:
        raise SessionInvariantError("Session Turn trace digest does not match its trace")
    calls = _call_occurrences(trace)
    results = _result_occurrences(trace)
    calls_by_id: dict[str, list[_CallOccurrence]] = defaultdict(list)
    results_by_id: dict[str, list[_ResultOccurrence]] = defaultdict(list)
    for call in calls:
        calls_by_id[call.call_id].append(call)
    for result in results:
        results_by_id[result.call_id].append(result)

    pending: list[tuple[int, TurnActionDetail]] = []
    occurrence = 0
    for call_id in sorted(set(calls_by_id) | set(results_by_id)):
        call_group = calls_by_id[call_id]
        result_group = results_by_id[call_id]
        if len(call_group) == 1 and len(result_group) == 1:
            call = call_group[0]
            result = result_group[0]
            issue = (
                ActionPairingIssue.NAME_MISMATCH
                if call.action_name != result.action_name
                else None
            )
            pending.append(
                (
                    min(call.trace_index, result.trace_index),
                    _detail(
                        occurrence,
                        call=call,
                        result=result,
                        issue=issue,
                    ),
                )
            )
            occurrence += 1
            continue

        call_issue = (
            ActionPairingIssue.DUPLICATE_CALL_ID
            if len(call_group) > 1
            else (
                ActionPairingIssue.DUPLICATE_RESULT
                if len(result_group) > 1
                else ActionPairingIssue.MISSING_RESULT
            )
        )
        result_issue = (
            ActionPairingIssue.DUPLICATE_RESULT
            if len(result_group) > 1
            else (
                ActionPairingIssue.DUPLICATE_CALL_ID
                if len(call_group) > 1
                else ActionPairingIssue.ORPHAN_RESULT
            )
        )
        for call in call_group:
            pending.append(
                (
                    call.trace_index,
                    _detail(occurrence, call=call, issue=call_issue),
                )
            )
            occurrence += 1
        for result in result_group:
            pending.append(
                (
                    result.trace_index,
                    _detail(occurrence, result=result, issue=result_issue),
                )
            )
            occurrence += 1

    pending.sort(key=lambda item: (item[0], item[1].occurrence))
    details = tuple(
        replace(detail, occurrence=index)
        for index, (_, detail) in enumerate(pending)
    )
    return TurnActionProjection(
        trace_digest=actual_digest,
        details=details,
        call_count=len(calls),
        result_count=len(results),
    )


def _call_occurrences(trace: tuple[JsonObject, ...]) -> tuple[_CallOccurrence, ...]:
    values: list[_CallOccurrence] = []
    for trace_index, entry in enumerate(trace):
        if entry.get("kind") != "decision" or entry.get("phase") != "phase2":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            raise SessionInvariantError("Session trace assistant tool_calls must be a list")
        for call in tool_calls:
            if not isinstance(call, dict):
                raise SessionInvariantError("Session trace tool call must be an object")
            if call.get("kind") != "action":
                continue
            values.append(
                _CallOccurrence(
                    call_id=_required_text(call, "id", owner="Action call"),
                    action_name=_required_text(call, "name", owner="Action call"),
                    trace_index=trace_index,
                    cycle_id=_optional_text(entry.get("cycle_id")),
                    phase=_optional_text(entry.get("phase")),
                )
            )
    return tuple(values)


def _result_occurrences(
    trace: tuple[JsonObject, ...],
) -> tuple[_ResultOccurrence, ...]:
    values: list[_ResultOccurrence] = []
    for trace_index, entry in enumerate(trace):
        if entry.get("kind") != "action_result" or entry.get("phase") != "phase3":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "tool_result":
            continue
        call_id = _required_text(message, "call_id", owner="Action result")
        action_name = _required_text(message, "tool_name", owner="Action result")
        envelope_value = _single_json_content(message)
        try:
            envelope = ActionResultEnvelope.from_json(envelope_value)
        except ActionInvariantError as exc:
            raise SessionInvariantError(
                f"Session trace contains an invalid Action result: {call_id}"
            ) from exc
        if envelope.action_name != action_name:
            raise SessionInvariantError(
                f"Session trace Action result envelope name mismatch: {call_id}"
            )
        outer_status = message.get("status")
        expected_outer = (
            "ok" if envelope.status is ActionResultStatus.SUCCESS else "error"
        )
        if outer_status != expected_outer:
            raise SessionInvariantError(
                f"Session trace Action result status mismatch: {call_id}"
            )
        values.append(
            _ResultOccurrence(
                call_id=call_id,
                action_name=action_name,
                trace_index=trace_index,
                cycle_id=_optional_text(entry.get("cycle_id")),
                phase=_optional_text(entry.get("phase")),
                envelope=envelope,
            )
        )
    return tuple(values)


def _detail(
    occurrence: int,
    *,
    call: _CallOccurrence | None = None,
    result: _ResultOccurrence | None = None,
    issue: ActionPairingIssue | None = None,
) -> TurnActionDetail:
    if call is None and result is None:
        raise SessionInvariantError("Action detail requires a call or result")
    if call is None:
        assert result is not None
        action_name = result.action_name
        call_id = result.call_id
    else:
        action_name = call.action_name
        call_id = call.call_id
    envelope = result.envelope if result is not None else None
    return TurnActionDetail(
        occurrence=occurrence,
        call_id=call_id,
        action_name=action_name,
        call_trace_index=call.trace_index if call is not None else None,
        result_trace_index=result.trace_index if result is not None else None,
        cycle_id=(
            call.cycle_id
            if call is not None
            else (result.cycle_id if result is not None else "")
        ),
        phase=(
            call.phase
            if call is not None
            else (result.phase if result is not None else "")
        ),
        status=envelope.status if envelope is not None else None,
        stage=envelope.stage.value if envelope is not None else "",
        failure=(
            envelope.failure.to_json()
            if envelope is not None and envelope.failure is not None
            else None
        ),
        pairing_issue=issue,
    )


def _single_json_content(message: JsonObject) -> JsonObject:
    content = message.get("content")
    if not isinstance(content, list):
        raise SessionInvariantError("Session trace Action result content must be a list")
    values = [
        item.get("value")
        for item in content
        if isinstance(item, dict) and item.get("type") == "json"
    ]
    if len(values) != 1 or not isinstance(values[0], dict):
        raise SessionInvariantError(
            "Session trace Action result requires one JSON envelope"
        )
    return to_json_object(values[0])


def _required_text(value: Mapping[str, object], name: str, *, owner: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise SessionInvariantError(f"{owner} requires non-empty {name}")
    return item


def _optional_text(value: object) -> str:
    return value if isinstance(value, str) else ""
