"""Session-owned validation for immutable Turn records."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.context import is_canonical_trace_digest
from tinysoul.infra.json import JsonObject, to_json_object

from .action_history import TurnActionProjection, project_turn_actions
from .errors import SessionInvariantError
from .models import SessionHistoryKind, SessionRecord


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


def _validate_background(
    background: JsonObject,
    *,
    record: SessionRecord,
    turn_id: str,
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
    expected: tuple[tuple[str, object], ...] = (
        ("kind", "session_turn"),
        ("ref", record.ref),
        ("turn_id", turn_id),
        ("trace_digest", trace_digest),
        ("trace_summary", trace_summary),
        ("action_outcome_summary", projection.outcome_summary()),
        ("exhausted", exhausted),
    )
    for field, value in expected:
        if background.get(field) != value:
            raise SessionInvariantError(
                f"Session Turn background {field} is inconsistent: {record.ref}"
            )
    _required_strings(
        background.get("user_ask"), label="background.user_ask", ref=record.ref
    )
    actions = _required_objects(
        background.get("actions"), label="background.actions", ref=record.ref
    )
    _required_text(
        background.get("answer"),
        label="background.answer",
        ref=record.ref,
        allow_empty=True,
    )
    _required_strings(
        background.get("references"), label="background.references", ref=record.ref
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
