"""Session Background projections derived from immutable records."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import SessionContractError

from tinysoul.infra.json import JsonObject, to_json_object, to_json_value

from ..records.models import SessionTurnRecord
from .navigation import (
    action_collection_ref,
    action_outcomes,
    input_ref,
    resource_locator,
)


@dataclass(frozen=True)
class SessionBackgroundItem:
    """One Session-owned message projected into BackgroundContext."""

    item_id: str
    content: JsonObject

    def __post_init__(self) -> None:
        if not self.item_id:
            raise SessionContractError(
                "SessionBackgroundItem.item_id must be non-empty"
            )
        object.__setattr__(self, "content", to_json_object(self.content))


@dataclass(frozen=True)
class SessionBackgroundSnapshot:
    """Immutable Session history projection for one Turn."""

    revision: int
    items: tuple[SessionBackgroundItem, ...] = field(default_factory=tuple)
    refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise SessionContractError(
                "SessionBackgroundSnapshot.revision cannot be negative"
            )
        object.__setattr__(self, "items", tuple(self.items))
        if any(not isinstance(item, SessionBackgroundItem) for item in self.items):
            raise SessionContractError("Session view requires typed background items")
        ids = tuple(item.item_id for item in self.items)
        if len(ids) != len(set(ids)):
            raise SessionContractError(
                "SessionBackgroundSnapshot.items must have unique ids"
            )
        refs = tuple(self.refs)
        if len(set(refs)) != len(refs) or any(
            not isinstance(ref, str) or not ref for ref in refs
        ):
            raise SessionContractError(
                "Session view references must be unique non-empty strings"
            )
        object.__setattr__(self, "refs", refs)


_TURN_ASK_ITEM_MAX_CHARS = 1200
_TURN_ASK_TOTAL_MAX_CHARS = 2400
_TURN_ANSWER_MAX_CHARS = 1800


def project_turn_background(record: SessionTurnRecord) -> JsonObject:
    """Project one completed Turn into the fixed next-Turn Background."""

    value: JsonObject = {
        "kind": "session_turn",
        "ref": record.ref,
        "status": record.status.value,
        "day": record.day,
        "user_ask": to_json_value(
            _bounded_asks(tuple(item.text for item in record.inputs))
        ),
    }
    selected_asks = _bounded_asks(tuple(item.text for item in record.inputs))
    value["excerpted"] = len(selected_asks) != len(record.inputs) or selected_asks != [
        item.text for item in record.inputs
    ]
    value["inputs"] = {
        "count": len(record.inputs),
        "first_ref": input_ref(record.ref, 0),
    }
    if record.output is not None:
        value["answer"] = _clip(record.output.text, _TURN_ANSWER_MAX_CHARS)
        value["excerpted"] = (
            bool(value["excerpted"]) or len(record.output.text) > _TURN_ANSWER_MAX_CHARS
        )
        if record.output.references:
            value["references"] = [
                resource_locator(record, link) for link in record.output.references
            ]
    if record.exhausted:
        value["exhausted"] = True
    failures = (record.failure,) if record.failure is not None else ()
    failures += record.finish_failures
    if failures:
        value["failures"] = [
            {"kind": item.kind, "message": item.message[:240]} for item in failures
        ]
    outcomes = action_outcomes(record)
    if outcomes:
        value["actions"] = {
            "ref": action_collection_ref(record.ref),
            "count": len(record.actions),
            "outcomes": list(outcomes),
        }
    return to_json_object(value)


def project_map_entry(*, day: str, total: int, projected: int) -> JsonObject:
    return {
        "kind": "session_map",
        "ref": "session:map",
        "day": day,
        "total_turns": total,
        "projected_turns": projected,
        "omitted_turns": total - projected,
        "coverage": "all" if total == projected else "recent",
        "inspect_action": "core.context.inspect",
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
