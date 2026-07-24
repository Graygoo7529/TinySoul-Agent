"""Session-owned validation for immutable history records."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.context import is_canonical_trace_digest
from tinysoul.infra.json import JsonObject, to_json_object

from .action_history import TurnActionProjection, project_turn_actions
from .background import (
    project_summary_background,
    project_turn_background,
    summary_ref,
    validate_turn_background_actions,
)
from .errors import SessionContractError, SessionInvariantError
from .models import SessionHistoryItem, SessionHistoryKind, SessionRecord


_TURN_CONTENT_FIELDS = frozenset(
    {"day", "background", "completion", "action_history", "output", "exhausted"}
)
_TURN_COMPLETION_FIELDS = frozenset(
    {
        "turn_id",
        "inputs",
        "working",
        "background_links",
        "trace_summary",
        "trace_digest",
        "trace",
        "trace_heap",
    }
)
_TURN_BACKGROUND_FIELDS = frozenset(
    {
        "kind",
        "ref",
        "turn_id",
        "user_ask",
        "actions",
        "answer",
        "references",
        "exhausted",
        "action_outcome_summary",
        "trace_summary",
        "trace_digest",
    }
)
_SUMMARY_CONTENT_FIELDS = frozenset(
    {"day", "background", "child_refs", "children"}
)


@dataclass(frozen=True)
class ValidatedTurnRecord:
    """Trusted view of one schema v3 Turn record."""

    record: SessionRecord
    day: str
    turn_id: str
    background: JsonObject
    completion: JsonObject
    inputs: tuple[JsonObject, ...]
    working: JsonObject
    background_links: tuple[str, ...]
    trace_summary: JsonObject
    trace: tuple[JsonObject, ...]
    trace_digest: str
    action_projection: TurnActionProjection
    background_actions: tuple[JsonObject, ...]
    output: JsonObject | None
    exhausted: bool


@dataclass(frozen=True)
class ValidatedSummaryRecord:
    """Trusted view of one deterministic schema v3 Summary record."""

    record: SessionRecord
    day: str
    background: JsonObject
    child_refs: tuple[str, ...]
    children: tuple[SessionHistoryItem, ...]


def validate_turn_record(record: SessionRecord) -> ValidatedTurnRecord:
    """Validate all intrinsic and deterministically derived Turn facts."""

    if record.kind is not SessionHistoryKind.TURN:
        raise SessionInvariantError(
            f"Session record is not a Turn record: {record.ref}"
        )
    _require_exact_fields(
        record.content,
        expected=_TURN_CONTENT_FIELDS,
        owner=f"Session Turn record {record.ref}",
    )
    day = _required_text(record.content.get("day"), label="day", ref=record.ref)
    background = _required_object(
        record.content.get("background"), label="background", ref=record.ref
    )
    completion = _required_object(
        record.content.get("completion"), label="completion", ref=record.ref
    )
    _require_exact_fields(
        completion,
        expected=_TURN_COMPLETION_FIELDS,
        owner=f"Session Turn completion {record.ref}",
    )
    turn_id = _required_text(
        completion.get("turn_id"), label="turn_id", ref=record.ref
    )
    if record.ref != f"session:turn/{turn_id}":
        raise SessionInvariantError(
            f"Session Turn record identity is inconsistent: {record.ref}"
        )
    inputs = _required_objects(
        completion.get("inputs"), label="inputs", ref=record.ref
    )
    working = _required_object(
        completion.get("working"), label="working", ref=record.ref
    )
    background_links = _required_strings(
        completion.get("background_links"),
        label="background_links",
        ref=record.ref,
        unique=True,
    )
    trace_summary = _required_object(
        completion.get("trace_summary"), label="trace_summary", ref=record.ref
    )
    trace_digest = _required_text(
        completion.get("trace_digest"), label="trace_digest", ref=record.ref
    )
    if not is_canonical_trace_digest(trace_digest):
        raise SessionInvariantError(
            f"Session Turn record has an invalid trace digest: {record.ref}"
        )
    trace = _required_objects(
        completion.get("trace"), label="trace", ref=record.ref
    )
    _required_object(completion.get("trace_heap"), label="trace_heap", ref=record.ref)
    projection = project_turn_actions(trace, expected_digest=trace_digest)
    stored_action_history = _required_object(
        record.content.get("action_history"),
        label="action_history",
        ref=record.ref,
    )
    if stored_action_history != projection.summary_json():
        raise SessionInvariantError(
            f"Session Turn Action history projection is inconsistent: {record.ref}"
        )
    output_value = record.content.get("output")
    if output_value is not None and not isinstance(output_value, dict):
        raise SessionInvariantError(
            f"Session Turn output is not an object: {record.ref}"
        )
    output = to_json_object(output_value) if isinstance(output_value, dict) else None
    exhausted = record.content.get("exhausted")
    if not isinstance(exhausted, bool):
        raise SessionInvariantError(
            f"Session Turn exhausted flag is invalid: {record.ref}"
        )
    background_actions = _validate_background(
        background,
        record=record,
        turn_id=turn_id,
        inputs=inputs,
        output=output,
        trace_digest=trace_digest,
        trace_summary=trace_summary,
        projection=projection,
        exhausted=exhausted,
    )
    return ValidatedTurnRecord(
        record=record,
        day=day,
        turn_id=turn_id,
        background=background,
        completion=completion,
        inputs=inputs,
        working=working,
        background_links=background_links,
        trace_summary=trace_summary,
        trace=trace,
        trace_digest=trace_digest,
        action_projection=projection,
        background_actions=background_actions,
        output=output,
        exhausted=exhausted,
    )


def validate_summary_record(record: SessionRecord) -> ValidatedSummaryRecord:
    """Validate one Summary identity and its deterministic Background."""

    if record.kind is not SessionHistoryKind.SUMMARY:
        raise SessionInvariantError(
            f"Session record is not a Summary record: {record.ref}"
        )
    _require_exact_fields(
        record.content,
        expected=_SUMMARY_CONTENT_FIELDS,
        owner=f"Session Summary record {record.ref}",
    )
    day = _required_text(record.content.get("day"), label="day", ref=record.ref)
    background = _required_object(
        record.content.get("background"), label="background", ref=record.ref
    )
    child_refs = _required_strings(
        record.content.get("child_refs"),
        label="child_refs",
        ref=record.ref,
        unique=True,
    )
    raw_children = _required_objects(
        record.content.get("children"), label="children", ref=record.ref
    )
    if len(raw_children) < 2:
        raise SessionInvariantError(
            f"Session Summary record requires at least two children: {record.ref}"
        )
    try:
        children = tuple(SessionHistoryItem.from_json(item) for item in raw_children)
    except SessionContractError as exc:
        raise SessionInvariantError(
            f"Session Summary record contains an invalid child: {record.ref}"
        ) from exc
    if tuple(child.ref for child in children) != child_refs:
        raise SessionInvariantError(
            f"Session Summary record child refs are inconsistent: {record.ref}"
        )
    if summary_ref(day, child_refs) != record.ref:
        raise SessionInvariantError(
            f"Session Summary record identity is inconsistent: {record.ref}"
        )
    if project_summary_background(record.ref, children) != background:
        raise SessionInvariantError(
            f"Session Summary record background is inconsistent: {record.ref}"
        )
    return ValidatedSummaryRecord(
        record=record,
        day=day,
        background=background,
        child_refs=child_refs,
        children=children,
    )


def _validate_background(
    background: JsonObject,
    *,
    record: SessionRecord,
    turn_id: str,
    inputs: tuple[JsonObject, ...],
    output: JsonObject | None,
    trace_digest: str,
    trace_summary: JsonObject,
    projection: TurnActionProjection,
    exhausted: bool,
) -> tuple[JsonObject, ...]:
    _require_exact_fields(
        background,
        expected=_TURN_BACKGROUND_FIELDS,
        owner=f"Session Turn background {record.ref}",
    )
    actions = _required_objects(
        background.get("actions"), label="background.actions", ref=record.ref
    )
    validate_turn_background_actions(
        actions,
        projection=projection,
        ref=record.ref,
    )
    expected = project_turn_background(
        ref=record.ref,
        turn_id=turn_id,
        inputs=inputs,
        output=output,
        exhausted=exhausted,
        trace_summary=trace_summary,
        trace_digest=trace_digest,
        action_outcome_summary=projection.outcome_summary(),
        actions=actions,
    )
    if background != expected:
        raise SessionInvariantError(
            f"Session Turn background is inconsistent with source facts: {record.ref}"
        )
    return actions


def _require_exact_fields(
    value: JsonObject,
    *,
    expected: frozenset[str],
    owner: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise SessionInvariantError(f"{owner} fields are invalid: {'; '.join(details)}")


def _required_text(
    value: object,
    *,
    label: str,
    ref: str,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise SessionInvariantError(
            f"Session Turn {label} must be non-empty text: {ref}"
        )
    return value


def _required_object(value: object, *, label: str, ref: str) -> JsonObject:
    if not isinstance(value, dict):
        raise SessionInvariantError(
            f"Session Turn {label} must be an object: {ref}"
        )
    return to_json_object(value)


def _required_objects(
    value: object,
    *,
    label: str,
    ref: str,
) -> tuple[JsonObject, ...]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SessionInvariantError(
            f"Session Turn {label} must be an object list: {ref}"
        )
    return tuple(to_json_object(item) for item in value if isinstance(item, dict))


def _required_strings(
    value: object,
    *,
    label: str,
    ref: str,
    unique: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise SessionInvariantError(
            f"Session Turn {label} must be a non-empty string list: {ref}"
        )
    items = tuple(item for item in value if isinstance(item, str))
    if unique and len(set(items)) != len(items):
        raise SessionInvariantError(
            f"Session Turn {label} must contain unique values: {ref}"
        )
    return items
