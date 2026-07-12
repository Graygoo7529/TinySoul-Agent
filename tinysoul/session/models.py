"""Persistent Session history models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import time_ns

from tinysoul.infra.json import JsonObject, to_json_object

from .errors import SessionContractError


class SessionHistoryKind(StrEnum):
    TURN = "turn"
    SUMMARY = "summary"


@dataclass(frozen=True)
class SessionHistoryItem:
    """One visible node in the bounded cross-Turn history head."""

    item_id: str
    ref: str
    kind: SessionHistoryKind
    background: JsonObject
    char_count: int
    child_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.item_id or not self.ref:
            raise SessionContractError("Session history item id and ref must be non-empty")
        if not isinstance(self.kind, SessionHistoryKind):
            raise SessionContractError("Session history item kind is invalid")
        if self.char_count < 0:
            raise SessionContractError("Session history char_count cannot be negative")
        if any(not ref for ref in self.child_refs):
            raise SessionContractError("Session history child refs must be non-empty")
        object.__setattr__(self, "background", to_json_object(self.background))
        object.__setattr__(self, "child_refs", tuple(self.child_refs))

    def to_json(self) -> JsonObject:
        return {
            "item_id": self.item_id,
            "ref": self.ref,
            "kind": self.kind.value,
            "background": self.background,
            "char_count": self.char_count,
            "child_refs": list(self.child_refs),
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "SessionHistoryItem":
        kind_value = _str(value, "kind")
        try:
            kind = SessionHistoryKind(kind_value)
        except ValueError as exc:
            raise SessionContractError(
                f"Unknown Session history kind: {kind_value}"
            ) from exc
        return cls(
            item_id=_str(value, "item_id"),
            ref=_str(value, "ref"),
            kind=kind,
            background=_object(value, "background"),
            char_count=_int(value, "char_count"),
            child_refs=_strings(value, "child_refs"),
        )


@dataclass(frozen=True)
class SessionManifest:
    """Authoritative visible Session head for one calendar day."""

    day: str
    revision: int = 0
    items: tuple[SessionHistoryItem, ...] = field(default_factory=tuple)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.day:
            raise SessionContractError("Session manifest day must be non-empty")
        if self.schema_version != 1:
            raise SessionContractError("Session manifest schema_version must be 1")
        if self.revision < 0:
            raise SessionContractError("Session manifest revision cannot be negative")
        ids = tuple(item.item_id for item in self.items)
        refs = tuple(item.ref for item in self.items)
        if len(ids) != len(set(ids)) or len(refs) != len(set(refs)):
            raise SessionContractError("Session manifest items must be unique")

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "day": self.day,
            "revision": self.revision,
            "items": [item.to_json() for item in self.items],
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "SessionManifest":
        raw_items = value.get("items", [])
        if not isinstance(raw_items, list):
            raise SessionContractError("Session manifest items must be a list")
        items: list[SessionHistoryItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise SessionContractError("Session manifest items must be objects")
            items.append(SessionHistoryItem.from_json(to_json_object(raw)))
        return cls(
            schema_version=_int(value, "schema_version"),
            day=_str(value, "day"),
            revision=_int(value, "revision"),
            items=tuple(items),
        )


@dataclass(frozen=True)
class SessionRecord:
    """Immutable detail record addressed by a Session ref."""

    ref: str
    kind: SessionHistoryKind
    content: JsonObject
    recorded_at_ns: int = field(default_factory=time_ns)
    schema_version: int = 2

    def __post_init__(self) -> None:
        if not self.ref:
            raise SessionContractError("Session record ref must be non-empty")
        if self.schema_version != 2:
            raise SessionContractError("Session record schema_version must be 2")
        if (
            isinstance(self.recorded_at_ns, bool)
            or not isinstance(self.recorded_at_ns, int)
            or self.recorded_at_ns < 0
        ):
            raise SessionContractError(
                "Session record recorded_at_ns must be a non-negative integer"
            )
        object.__setattr__(self, "content", to_json_object(self.content))

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "ref": self.ref,
            "kind": self.kind.value,
            "recorded_at_ns": self.recorded_at_ns,
            "content": self.content,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "SessionRecord":
        kind_value = _str(value, "kind")
        try:
            kind = SessionHistoryKind(kind_value)
        except ValueError as exc:
            raise SessionContractError(
                f"Unknown Session record kind: {kind_value}"
            ) from exc
        schema_version = value.get("schema_version", 1)
        if schema_version not in {1, 2}:
            raise SessionContractError(
                f"Unsupported Session record schema_version: {schema_version}"
            )
        recorded_at_ns = value.get("recorded_at_ns", 0)
        if (
            isinstance(recorded_at_ns, bool)
            or not isinstance(recorded_at_ns, int)
            or recorded_at_ns < 0
        ):
            raise SessionContractError(
                "Session record recorded_at_ns must be a non-negative integer"
            )
        return cls(
            ref=_str(value, "ref"),
            kind=kind,
            content=_object(value, "content"),
            recorded_at_ns=recorded_at_ns,
        )


def _str(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise SessionContractError(f"Session field must be non-empty text: {name}")
    return item


def _int(value: JsonObject, name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise SessionContractError(f"Session field must be non-negative int: {name}")
    return item


def _object(value: JsonObject, name: str) -> JsonObject:
    item = value.get(name)
    if not isinstance(item, dict):
        raise SessionContractError(f"Session field must be an object: {name}")
    return to_json_object(item)


def _strings(value: JsonObject, name: str) -> tuple[str, ...]:
    item = value.get(name, [])
    if not isinstance(item, list) or any(
        not isinstance(entry, str) or not entry for entry in item
    ):
        raise SessionContractError(f"Session field must be a string list: {name}")
    return tuple(entry for entry in item if isinstance(entry, str))
