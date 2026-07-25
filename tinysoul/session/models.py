"""Immutable Session business records and active-head manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import re
from time import time_ns

from tinysoul.action import ActionInvariantError, ActionLocalFailure
from tinysoul.infra.json import JsonObject, dumps_json, to_json_object

from .errors import SessionContractError


SESSION_RECORD_SCHEMA_VERSION = 4
SESSION_MANIFEST_SCHEMA_VERSION = 2
_TURN_REF = re.compile(r"^session:turn/([a-z0-9_-]+)$")
_SUMMARY_REF = re.compile(r"^session:summary/([a-z0-9_-]+)$")


class SessionRecordKind(StrEnum):
    TURN = "turn"
    SUMMARY = "summary"


class SessionActionOutcome(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class SessionInputRecord:
    text: str
    received_at: float

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise SessionContractError("Session input text must be non-empty")
        if (
            isinstance(self.received_at, bool)
            or not isinstance(self.received_at, (int, float))
            or self.received_at < 0
        ):
            raise SessionContractError("Session input timestamp must be non-negative")

    def to_json(self) -> JsonObject:
        return {"text": self.text, "received_at": float(self.received_at)}

    @classmethod
    def from_json(cls, value: object) -> "SessionInputRecord":
        item = _exact_object(value, {"text", "received_at"}, "Session input")
        return cls(
            text=_required_text(item, "text"),
            received_at=_non_negative_number(item, "received_at"),
        )


@dataclass(frozen=True)
class SessionOutputRecord:
    text: str
    references: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise SessionContractError("Session output text must be non-empty")
        object.__setattr__(
            self,
            "references",
            _non_empty_strings(self.references, "Session output references"),
        )

    def to_json(self) -> JsonObject:
        value: JsonObject = {"text": self.text}
        if self.references:
            value["references"] = list(self.references)
        return value

    @classmethod
    def from_json(cls, value: object) -> "SessionOutputRecord":
        item = _limited_object(value, {"text", "references"}, "Session output")
        return cls(
            text=_required_text(item, "text"),
            references=_string_list(item.get("references", []), "references"),
        )


@dataclass(frozen=True)
class SessionActionRecord:
    action: str
    request: JsonObject
    outcome: SessionActionOutcome
    result: JsonObject = field(default_factory=dict)
    failure: ActionLocalFailure | None = None
    references: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.action, str) or not self.action:
            raise SessionContractError("Session Action name must be non-empty")
        if not isinstance(self.outcome, SessionActionOutcome):
            raise SessionContractError("Session Action outcome is invalid")
        object.__setattr__(self, "request", to_json_object(self.request))
        result = to_json_object(self.result)
        if "failure" in result:
            raise SessionContractError("Session Action result cannot contain failure")
        object.__setattr__(self, "result", result)
        if self.failure is not None and not isinstance(
            self.failure,
            ActionLocalFailure,
        ):
            raise SessionContractError(
                "Session Action failure must be an ActionLocalFailure"
            )
        object.__setattr__(
            self,
            "references",
            _non_empty_strings(self.references, "Session Action references"),
        )
        if (
            self.outcome is SessionActionOutcome.SUCCESS
            and self.failure is not None
        ):
            raise SessionContractError("Successful Session Action cannot have failure")
        if self.outcome is not SessionActionOutcome.SUCCESS and self.failure is None:
            raise SessionContractError("Failed Session Action requires failure facts")

    def to_json(self) -> JsonObject:
        value: JsonObject = {
            "action": self.action,
            "request": self.request,
            "outcome": self.outcome.value,
        }
        if self.result:
            value["result"] = self.result
        if self.failure is not None:
            value["failure"] = self.failure.to_json()
        if self.references:
            value["references"] = list(self.references)
        return value

    @classmethod
    def from_json(cls, value: object) -> "SessionActionRecord":
        item = _limited_object(
            value,
            {"action", "request", "outcome", "result", "failure", "references"},
            "Session Action",
        )
        try:
            outcome = SessionActionOutcome(item.get("outcome"))
        except (TypeError, ValueError) as exc:
            raise SessionContractError("Session Action outcome is invalid") from exc
        return cls(
            action=_required_text(item, "action"),
            request=_required_object(item, "request"),
            outcome=outcome,
            result=_optional_object(item, "result"),
            failure=_optional_action_failure(item),
            references=_string_list(item.get("references", []), "references"),
        )


@dataclass(frozen=True)
class SessionTurnRecord:
    ref: str
    day: str
    inputs: tuple[SessionInputRecord, ...]
    working: JsonObject
    background_links: tuple[str, ...]
    output: SessionOutputRecord | None
    exhausted: bool
    actions: tuple[SessionActionRecord, ...]
    recorded_at_ns: int = field(default_factory=time_ns)
    kind: SessionRecordKind = field(default=SessionRecordKind.TURN, init=False)
    schema_version: int = field(default=SESSION_RECORD_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if _TURN_REF.fullmatch(self.ref) is None:
            raise SessionContractError("Session Turn ref is invalid")
        _require_day(self.day)
        inputs = tuple(self.inputs)
        if not inputs or any(not isinstance(item, SessionInputRecord) for item in inputs):
            raise SessionContractError("Session Turn requires typed inputs")
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "working", to_json_object(self.working))
        object.__setattr__(
            self,
            "background_links",
            _non_empty_strings(
                self.background_links,
                "Session Turn background links",
                unique=True,
            ),
        )
        if self.output is not None and not isinstance(self.output, SessionOutputRecord):
            raise SessionContractError("Session Turn output is invalid")
        if not isinstance(self.exhausted, bool):
            raise SessionContractError("Session Turn exhausted must be a boolean")
        actions = tuple(self.actions)
        if any(not isinstance(item, SessionActionRecord) for item in actions):
            raise SessionContractError("Session Turn actions must be typed records")
        object.__setattr__(self, "actions", actions)
        _require_recorded_at(self.recorded_at_ns)

    @property
    def turn_id(self) -> str:
        match = _TURN_REF.fullmatch(self.ref)
        assert match is not None
        return match.group(1)

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "ref": self.ref,
            "day": self.day,
            "recorded_at_ns": self.recorded_at_ns,
            "inputs": [item.to_json() for item in self.inputs],
            "working": self.working,
            "background_links": list(self.background_links),
            "output": self.output.to_json() if self.output is not None else None,
            "exhausted": self.exhausted,
            "actions": [item.to_json() for item in self.actions],
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "SessionTurnRecord":
        _require_record_header(value, SessionRecordKind.TURN)
        _require_fields(
            value,
            {
                "schema_version",
                "kind",
                "ref",
                "day",
                "recorded_at_ns",
                "inputs",
                "working",
                "background_links",
                "output",
                "exhausted",
                "actions",
            },
            "Session Turn record",
        )
        raw_inputs = _required_list(value, "inputs")
        raw_actions = _required_list(value, "actions")
        raw_output = value.get("output")
        return cls(
            ref=_required_text(value, "ref"),
            day=_required_text(value, "day"),
            recorded_at_ns=_non_negative_int(value, "recorded_at_ns"),
            inputs=tuple(SessionInputRecord.from_json(item) for item in raw_inputs),
            working=_required_object(value, "working"),
            background_links=_string_list(
                value.get("background_links", []), "background_links"
            ),
            output=(
                SessionOutputRecord.from_json(raw_output)
                if raw_output is not None
                else None
            ),
            exhausted=_required_bool(value, "exhausted"),
            actions=tuple(SessionActionRecord.from_json(item) for item in raw_actions),
        )


@dataclass(frozen=True)
class SessionSummaryRecord:
    ref: str
    day: str
    child_refs: tuple[str, ...]
    recorded_at_ns: int = field(default_factory=time_ns)
    kind: SessionRecordKind = field(default=SessionRecordKind.SUMMARY, init=False)
    schema_version: int = field(default=SESSION_RECORD_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if _SUMMARY_REF.fullmatch(self.ref) is None:
            raise SessionContractError("Session Summary ref is invalid")
        _require_day(self.day)
        children = _non_empty_strings(
            self.child_refs,
            "Session Summary child refs",
            unique=True,
        )
        if len(children) < 2:
            raise SessionContractError("Session Summary requires at least two children")
        for ref in children:
            session_ref_kind(ref)
        object.__setattr__(self, "child_refs", children)
        _require_recorded_at(self.recorded_at_ns)

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "ref": self.ref,
            "day": self.day,
            "recorded_at_ns": self.recorded_at_ns,
            "child_refs": list(self.child_refs),
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "SessionSummaryRecord":
        _require_record_header(value, SessionRecordKind.SUMMARY)
        _require_fields(
            value,
            {
                "schema_version",
                "kind",
                "ref",
                "day",
                "recorded_at_ns",
                "child_refs",
            },
            "Session Summary record",
        )
        return cls(
            ref=_required_text(value, "ref"),
            day=_required_text(value, "day"),
            recorded_at_ns=_non_negative_int(value, "recorded_at_ns"),
            child_refs=_string_list(value.get("child_refs", []), "child_refs"),
        )


SessionRecord = SessionTurnRecord | SessionSummaryRecord


@dataclass(frozen=True)
class SessionManifest:
    day: str
    revision: int = 0
    refs: tuple[str, ...] = field(default_factory=tuple)
    schema_version: int = field(default=SESSION_MANIFEST_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _require_day(self.day)
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 0:
            raise SessionContractError("Session manifest revision cannot be negative")
        refs = _non_empty_strings(self.refs, "Session manifest refs", unique=True)
        for ref in refs:
            session_ref_kind(ref)
        object.__setattr__(self, "refs", refs)

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "day": self.day,
            "revision": self.revision,
            "refs": list(self.refs),
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "SessionManifest":
        _require_fields(
            value,
            {"schema_version", "day", "revision", "refs"},
            "Session manifest",
        )
        if value.get("schema_version") != SESSION_MANIFEST_SCHEMA_VERSION:
            raise SessionContractError(
                f"Session manifest schema_version must be {SESSION_MANIFEST_SCHEMA_VERSION}"
            )
        return cls(
            day=_required_text(value, "day"),
            revision=_non_negative_int(value, "revision"),
            refs=_string_list(value.get("refs", []), "refs"),
        )


def session_record_from_json(value: JsonObject) -> SessionRecord:
    if value.get("schema_version") != SESSION_RECORD_SCHEMA_VERSION:
        raise SessionContractError(
            f"Session record schema_version must be {SESSION_RECORD_SCHEMA_VERSION}"
        )
    kind = value.get("kind")
    if kind == SessionRecordKind.TURN.value:
        return SessionTurnRecord.from_json(value)
    if kind == SessionRecordKind.SUMMARY.value:
        return SessionSummaryRecord.from_json(value)
    raise SessionContractError("Session record kind is invalid")


def session_ref_kind(ref: str) -> SessionRecordKind:
    if not isinstance(ref, str):
        raise SessionContractError("Session ref must be text")
    if _TURN_REF.fullmatch(ref) is not None:
        return SessionRecordKind.TURN
    if _SUMMARY_REF.fullmatch(ref) is not None:
        return SessionRecordKind.SUMMARY
    raise SessionContractError(f"Invalid Session ref: {ref}")


def summary_ref(day: str, child_refs: tuple[str, ...]) -> str:
    """Return the deterministic identity of one Summary index node."""

    _require_day(day)
    children = _non_empty_strings(
        child_refs,
        "Session Summary child refs",
        unique=True,
    )
    if len(children) < 2:
        raise SessionContractError("Session Summary requires at least two children")
    encoded = dumps_json({"day": day, "child_refs": list(children)}).encode("utf-8")
    return f"session:summary/summary_{sha256(encoded).hexdigest()[:16]}"


def same_record_facts(left: SessionRecord, right: SessionRecord) -> bool:
    left_value = left.to_json()
    right_value = right.to_json()
    left_value.pop("recorded_at_ns", None)
    right_value.pop("recorded_at_ns", None)
    return left_value == right_value


def _require_record_header(value: JsonObject, kind: SessionRecordKind) -> None:
    if value.get("schema_version") != SESSION_RECORD_SCHEMA_VERSION:
        raise SessionContractError(
            f"Session record schema_version must be {SESSION_RECORD_SCHEMA_VERSION}"
        )
    if value.get("kind") != kind.value:
        raise SessionContractError("Session record kind is inconsistent")


def _require_fields(value: JsonObject, fields: set[str], owner: str) -> None:
    if set(value) != fields:
        raise SessionContractError(f"{owner} fields are invalid")


def _require_day(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise SessionContractError("Session day must be non-empty")


def _require_recorded_at(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SessionContractError("Session recorded_at_ns must be non-negative")


def _limited_object(value: object, fields: set[str], owner: str) -> JsonObject:
    if not isinstance(value, dict):
        raise SessionContractError(f"{owner} must be an object")
    unknown = set(value) - fields
    if unknown:
        raise SessionContractError(f"{owner} contains unknown fields")
    return to_json_object(value)


def _exact_object(value: object, fields: set[str], owner: str) -> JsonObject:
    item = _limited_object(value, fields, owner)
    if set(item) != fields:
        raise SessionContractError(f"{owner} is missing required fields")
    return item


def _required_text(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise SessionContractError(f"Session field must be non-empty text: {name}")
    return item


def _required_object(value: JsonObject, name: str) -> JsonObject:
    item = value.get(name)
    if not isinstance(item, dict):
        raise SessionContractError(f"Session field must be an object: {name}")
    return to_json_object(item)


def _optional_object(value: JsonObject, name: str) -> JsonObject:
    item = value.get(name, {})
    if not isinstance(item, dict):
        raise SessionContractError(f"Session field must be an object: {name}")
    return to_json_object(item)


def _optional_action_failure(value: JsonObject) -> ActionLocalFailure | None:
    if "failure" not in value:
        return None
    try:
        return ActionLocalFailure.from_json(value["failure"])
    except ActionInvariantError as exc:
        raise SessionContractError(f"Session Action failure is invalid: {exc}") from exc


def _required_list(value: JsonObject, name: str) -> list[object]:
    item = value.get(name)
    if not isinstance(item, list):
        raise SessionContractError(f"Session field must be a list: {name}")
    return list(item)


def _required_bool(value: JsonObject, name: str) -> bool:
    item = value.get(name)
    if not isinstance(item, bool):
        raise SessionContractError(f"Session field must be a boolean: {name}")
    return item


def _non_negative_int(value: JsonObject, name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise SessionContractError(f"Session field must be non-negative int: {name}")
    return item


def _non_negative_number(value: JsonObject, name: str) -> float:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0:
        raise SessionContractError(f"Session field must be non-negative: {name}")
    return float(item)


def _string_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SessionContractError(f"Session field must be a string list: {name}")
    return _non_empty_strings(tuple(value), f"Session {name}")


def _non_empty_strings(
    values: tuple[object, ...] | tuple[str, ...],
    owner: str,
    *,
    unique: bool = False,
) -> tuple[str, ...]:
    items = tuple(values)
    if any(not isinstance(item, str) or not item for item in items):
        raise SessionContractError(f"{owner} must contain non-empty strings")
    result = tuple(item for item in items if isinstance(item, str))
    if unique and len(set(result)) != len(result):
        raise SessionContractError(f"{owner} must be unique")
    return result
