"""Session Background projections derived from immutable records."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject, to_json_object, to_json_value

from .models import SessionSummaryRecord, SessionTurnRecord
from .navigation import action_collection_ref, action_outcomes


_TURN_ASK_ITEM_MAX_CHARS = 1200
_TURN_ASK_TOTAL_MAX_CHARS = 2400
_TURN_ANSWER_MAX_CHARS = 1800


def project_turn_background(record: SessionTurnRecord) -> JsonObject:
    """Project one completed Turn into the fixed next-Turn Background."""

    value: JsonObject = {
        "kind": "session_turn",
        "ref": record.ref,
        "user_ask": to_json_value(
            _bounded_asks(tuple(item.text for item in record.inputs))
        ),
    }
    if record.output is not None:
        value["answer"] = _clip(record.output.text, _TURN_ANSWER_MAX_CHARS)
        if record.output.references:
            value["references"] = list(record.output.references)
    if record.exhausted:
        value["exhausted"] = True
    outcomes = action_outcomes(record)
    if outcomes:
        value["actions"] = {
            "ref": action_collection_ref(record.ref),
            "count": len(record.actions),
            "outcomes": list(outcomes),
        }
    return to_json_object(value)


def project_summary_background(
    record: SessionSummaryRecord,
    *,
    turn_count: int,
) -> JsonObject:
    """Project one immutable Summary as a compact heap navigation node."""

    return {
        "kind": "session_summary",
        "ref": record.ref,
        "turn_count": turn_count,
        "child_count": len(record.child_refs),
    }


def project_overflow_background() -> JsonObject:
    return {
        "kind": "session_overflow_head",
        "inspect_action": "core.session.inspect",
    }


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
