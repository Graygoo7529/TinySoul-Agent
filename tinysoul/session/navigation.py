"""Model-facing Session navigation derived from immutable Turn records."""

from __future__ import annotations

from dataclasses import dataclass
import re

from tinysoul.action import ActionResultEnvelope
from tinysoul.action.core.errors import ActionInvariantError
from tinysoul.infra.json import JsonObject, to_json_object

from .action_history import TurnActionDetail
from .errors import SessionContractError, SessionInvariantError


_TURN_REF_PATTERN = re.compile(r"^session:turn/([a-z0-9_-]+)$")
_ACTION_COLLECTION_PATTERN = re.compile(
    r"^(session:turn/[a-z0-9_-]+)#actions$"
)
_ACTION_OCCURRENCE_PATTERN = re.compile(
    r"^(session:turn/[a-z0-9_-]+)#action/([0-9]+)$"
)


@dataclass(frozen=True)
class SessionActionRef:
    """One parsed virtual ref below an immutable Session Turn."""

    turn_ref: str
    occurrence: int | None = None

    @property
    def is_collection(self) -> bool:
        return self.occurrence is None


def action_collection_ref(turn_ref: str) -> str:
    """Return the virtual Action collection ref for one Turn."""

    _require_turn_ref(turn_ref)
    return f"{turn_ref}#actions"


def action_occurrence_ref(turn_ref: str, occurrence: int) -> str:
    """Return the virtual ref for one deterministic Action occurrence."""

    _require_turn_ref(turn_ref)
    if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 0:
        raise SessionContractError("Session Action occurrence must be non-negative")
    return f"{turn_ref}#action/{occurrence}"


def parse_action_ref(ref: str) -> SessionActionRef | None:
    """Parse a virtual Action ref, returning None for ordinary history refs."""

    collection = _ACTION_COLLECTION_PATTERN.fullmatch(ref)
    if collection is not None:
        return SessionActionRef(turn_ref=collection.group(1))
    occurrence = _ACTION_OCCURRENCE_PATTERN.fullmatch(ref)
    if occurrence is not None:
        return SessionActionRef(
            turn_ref=occurrence.group(1),
            occurrence=int(occurrence.group(2)),
        )
    if "#" in ref:
        raise SessionContractError("Invalid Session Action ref")
    return None


def project_action_node(
    turn_ref: str,
    detail: TurnActionDetail,
) -> JsonObject:
    """Project one compact Action leaf for model navigation."""

    value: JsonObject = {
        "kind": "session_action",
        "ref": action_occurrence_ref(turn_ref, detail.occurrence),
        "action": detail.action_name,
        "outcome": _model_outcome(detail),
    }
    failure = _model_failure(detail)
    if failure:
        value["failure"] = failure
    return value


def project_action_recall(
    *,
    turn_ref: str,
    trace: tuple[JsonObject, ...],
    detail: TurnActionDetail,
) -> JsonObject:
    """Project one paired historical Action without framework trace locations."""

    ref = action_occurrence_ref(turn_ref, detail.occurrence)
    value: JsonObject = {
        "kind": "session_action",
        "ref": ref,
        "turn_ref": turn_ref,
        "action": detail.action_name,
        "outcome": _model_outcome(detail),
    }
    if detail.call_trace_index is not None:
        value["request"] = _call_arguments(trace, detail)
    if detail.result_trace_index is not None:
        envelope, references = _result_evidence(trace, detail)
        if envelope.payload:
            value["result"] = envelope.payload
        if references:
            value["references"] = list(references)
    failure = _model_failure(detail)
    if failure:
        value["failure"] = failure
    return to_json_object(value)


def _model_outcome(detail: TurnActionDetail) -> str:
    if detail.pairing_issue is not None:
        return "incomplete"
    if detail.status is None:
        return "incomplete"
    return detail.status.value


def _model_failure(detail: TurnActionDetail) -> JsonObject:
    if detail.failure is None:
        return {}
    value: JsonObject = {}
    for key in ("reason", "feedback"):
        item = detail.failure.get(key)
        if isinstance(item, str) and item:
            value[key] = item
    constraint = detail.failure.get("constraint")
    if isinstance(constraint, dict) and constraint:
        value["constraint"] = to_json_object(constraint)
    return value


def _call_arguments(
    trace: tuple[JsonObject, ...],
    detail: TurnActionDetail,
) -> JsonObject:
    assert detail.call_trace_index is not None
    entry = _trace_entry(trace, detail.call_trace_index)
    message = entry.get("message")
    if not isinstance(message, dict):
        raise SessionInvariantError("Session Action call message is invalid")
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        raise SessionInvariantError("Session Action call list is invalid")
    position = detail.call_position
    if position is None or position >= len(calls):
        raise SessionInvariantError("Session Action call position is invalid")
    match = calls[position]
    if (
        not isinstance(match, dict)
        or match.get("kind") != "action"
        or match.get("id") != detail.call_id
        or match.get("name") != detail.action_name
    ):
        raise SessionInvariantError("Session Action call evidence is inconsistent")
    arguments = match.get("arguments")
    if not isinstance(arguments, dict):
        raise SessionInvariantError("Session Action call arguments are invalid")
    return to_json_object(arguments)


def _result_evidence(
    trace: tuple[JsonObject, ...],
    detail: TurnActionDetail,
) -> tuple[ActionResultEnvelope, tuple[str, ...]]:
    assert detail.result_trace_index is not None
    entry = _trace_entry(trace, detail.result_trace_index)
    message = entry.get("message")
    if not isinstance(message, dict):
        raise SessionInvariantError("Session Action result message is invalid")
    content = message.get("content")
    if not isinstance(content, list):
        raise SessionInvariantError("Session Action result content is invalid")
    values = [
        item.get("value")
        for item in content
        if isinstance(item, dict) and item.get("type") == "json"
    ]
    if len(values) != 1:
        raise SessionInvariantError("Session Action result envelope is ambiguous")
    try:
        envelope = ActionResultEnvelope.from_json(values[0])
    except ActionInvariantError as exc:
        raise SessionInvariantError("Session Action result envelope is invalid") from exc
    if envelope.action_name != detail.action_name:
        raise SessionInvariantError("Session Action result name is inconsistent")
    raw_references = entry.get("origin_refs", [])
    if not isinstance(raw_references, list) or any(
        not isinstance(item, str) or not item for item in raw_references
    ):
        raise SessionInvariantError("Session Action result references are invalid")
    return envelope, tuple(
        item for item in raw_references if isinstance(item, str)
    )


def _trace_entry(trace: tuple[JsonObject, ...], index: int) -> JsonObject:
    if index >= len(trace):
        raise SessionInvariantError("Session Action trace location is out of range")
    return trace[index]


def _require_turn_ref(ref: str) -> None:
    if not isinstance(ref, str) or _TURN_REF_PATTERN.fullmatch(ref) is None:
        raise SessionContractError("Invalid Session Turn ref")
