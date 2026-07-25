"""Deterministic projections for persisted Session backgrounds."""

from __future__ import annotations

from hashlib import sha256

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object

from .action_history import TurnActionDetail, TurnActionProjection
from .errors import SessionInvariantError
from .models import SessionHistoryItem, SessionHistoryKind
from .navigation import action_collection_ref


_TURN_ASK_ITEM_MAX_CHARS = 1200
_TURN_ASK_TOTAL_MAX_CHARS = 2400
_TURN_ANSWER_MAX_CHARS = 1800
_SUMMARY_ASK_MAX_CHARS = 360
_SUMMARY_ANSWER_MAX_CHARS = 520


def select_turn_background_actions(
    projection: TurnActionProjection,
    *,
    action_names: frozenset[str],
    max_actions: int,
) -> tuple[JsonObject, ...]:
    """Select the commit-time Action detail materialization for one Turn."""

    values = tuple(
        _background_action_detail(item)
        for item in projection.details
        if item.action_name in action_names
    )
    return values[-max_actions:]


def validate_turn_background_actions(
    actions: tuple[JsonObject, ...],
    *,
    projection: TurnActionProjection,
    ref: str,
) -> None:
    """Prove stored policy-selected details came from the canonical trace."""

    expected = {
        item.occurrence: _background_action_detail(item)
        for item in projection.details
    }
    previous_occurrence = -1
    for action in actions:
        occurrence = action.get("occurrence")
        if (
            isinstance(occurrence, bool)
            or not isinstance(occurrence, int)
            or occurrence <= previous_occurrence
        ):
            raise SessionInvariantError(
                f"Session Turn background actions are not strictly ordered: {ref}"
            )
        candidate = expected.get(occurrence)
        if candidate is None or action != candidate:
            raise SessionInvariantError(
                f"Session Turn background action is inconsistent: {ref}"
            )
        previous_occurrence = occurrence


def project_turn_background(
    *,
    ref: str,
    turn_id: str,
    inputs: tuple[JsonObject, ...],
    output: JsonObject | None,
    exhausted: bool,
    trace_summary: JsonObject,
    trace_digest: str,
    action_outcome_summary: JsonObject,
    actions: tuple[JsonObject, ...],
) -> JsonObject:
    """Project source facts and one preserved policy selection into Background."""

    asks = tuple(
        text
        for item in inputs
        if isinstance((text := item.get("text")), str) and text
    )
    answer = ""
    references: list[str] = []
    if output is not None:
        raw_answer = output.get("text")
        if isinstance(raw_answer, str):
            answer = raw_answer
        raw_references = output.get("references", [])
        if isinstance(raw_references, list):
            references = [item for item in raw_references if isinstance(item, str)]
    return to_json_object(
        {
            "kind": "session_turn",
            "ref": ref,
            "turn_id": turn_id,
            "user_ask": _bounded_asks(asks),
            "actions": list(actions),
            "answer": _clip(answer, _TURN_ANSWER_MAX_CHARS),
            "references": references,
            "exhausted": exhausted,
            "action_outcome_summary": action_outcome_summary,
            "trace_summary": trace_summary,
            "trace_digest": trace_digest,
        }
    )


def project_summary_background(
    ref: str,
    children: tuple[SessionHistoryItem, ...],
) -> JsonObject:
    """Project one immutable Summary node from its ordered child items."""

    turns: list[JsonObject] = []
    for item in children:
        if item.kind is SessionHistoryKind.SUMMARY:
            turns.append(
                {
                    "kind": "summary",
                    "ref": item.ref,
                    "child_count": len(item.child_refs),
                }
            )
            continue
        turns.append(
            {
                "kind": "turn",
                "ref": item.ref,
                "user_ask": _clip_json_text(
                    item.background.get("user_ask"),
                    _SUMMARY_ASK_MAX_CHARS,
                ),
                "answer": _clip_json_text(
                    item.background.get("answer"),
                    _SUMMARY_ANSWER_MAX_CHARS,
                ),
            }
        )
    return to_json_object(
        {
            "kind": "session_summary",
            "ref": ref,
            "child_refs": [item.ref for item in children],
            "turns": turns,
        }
    )


def project_context_background(
    background: JsonObject,
    *,
    action_outcomes: tuple[JsonObject, ...] | None = None,
) -> JsonObject:
    """Project one persisted Session preview into automatic Context."""

    value = to_json_object(background)
    if value.get("kind") != "session_turn":
        value.pop("trace_digest", None)
        return value
    if action_outcomes is None:
        raise SessionInvariantError(
            "Session Turn model background requires validated Action outcomes"
        )
    ref = value.get("ref")
    if not isinstance(ref, str) or not ref:
        raise SessionInvariantError("Session Turn model background requires a ref")
    projected: JsonObject = {
        "kind": value.get("kind"),
        "ref": ref,
        "user_ask": value.get("user_ask"),
        "answer": value.get("answer"),
    }
    references = value.get("references")
    if isinstance(references, list) and references:
        projected["references"] = references
    if value.get("exhausted") is True:
        projected["exhausted"] = True
    if action_outcomes:
        projected["actions"] = {
            "ref": action_collection_ref(ref),
            "outcomes": list(action_outcomes),
        }
    return to_json_object(projected)


def summary_ref(day: str, child_refs: tuple[str, ...]) -> str:
    """Return the deterministic identity for one persisted Summary record."""

    digest = sha256(
        dumps_json(
            {
                "schema_version": 1,
                "day": day,
                "child_refs": list(child_refs),
            }
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"session:summary/summary_{digest}"


def _background_action_detail(item: TurnActionDetail) -> JsonObject:
    detail = item.to_json()
    failure = detail.pop("failure", None)
    if isinstance(failure, dict):
        detail["failure"] = {
            key: failure[key]
            for key in ("reason", "scope", "disposition")
            if key in failure
        }
    return detail


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _bounded_asks(asks: tuple[str, ...]) -> list[str]:
    selected: list[str] = []
    used = 0
    for text in reversed(asks):
        clipped = _clip(text, _TURN_ASK_ITEM_MAX_CHARS)
        if selected and used + len(clipped) > _TURN_ASK_TOTAL_MAX_CHARS:
            break
        selected.append(clipped)
        used += len(clipped)
    selected.reverse()
    return selected


def _clip_json_text(value: object, limit: int) -> str:
    if isinstance(value, str):
        return _clip(value, limit)
    if isinstance(value, list):
        return _clip("\n".join(item for item in value if isinstance(item, str)), limit)
    return ""
