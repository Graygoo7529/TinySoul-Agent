"""Persistent effective overlay for the mutable Agent Home working copy."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
from pathlib import Path, PurePosixPath

from tinysoul.infra.json import JsonObject, to_json_object
from ..errors import AgentHomeContractError


class HomeOverlayState(StrEnum):
    COPIED = "copied"
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class HomeOverlayRecord:
    relative_path: str
    state: HomeOverlayState
    baseline_digest: str = ""
    runtime_digest: str = ""
    size: int = 0
    mtime_ns: int = 0

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path)
        if not isinstance(self.state, HomeOverlayState):
            raise AgentHomeContractError("Home overlay state is invalid")
        if not isinstance(self.baseline_digest, str) or not isinstance(
            self.runtime_digest, str
        ):
            raise AgentHomeContractError("Home overlay digests must be strings")
        if self.state is HomeOverlayState.DELETED:
            if self.runtime_digest or self.size or self.mtime_ns:
                raise AgentHomeContractError(
                    "Deleted Home overlay records cannot describe runtime content"
                )
        elif not self.runtime_digest:
            raise AgentHomeContractError(
                "Active Home overlay records require a runtime digest"
            )
        if self.state is HomeOverlayState.CREATED and self.baseline_digest:
            raise AgentHomeContractError(
                "Created Home overlay records cannot have a baseline digest"
            )
        if (
            self.state in {HomeOverlayState.COPIED, HomeOverlayState.MODIFIED}
            and not self.baseline_digest
        ):
            raise AgentHomeContractError(
                "Copied or modified Home overlay records require a baseline digest"
            )
        if (
            self.state is HomeOverlayState.COPIED
            and self.runtime_digest != self.baseline_digest
        ):
            raise AgentHomeContractError(
                "Copied Home overlay content must equal its baseline"
            )
        if (
            isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or self.size < 0
        ):
            raise AgentHomeContractError("Home overlay size must be non-negative")
        if (
            isinstance(self.mtime_ns, bool)
            or not isinstance(self.mtime_ns, int)
            or self.mtime_ns < 0
        ):
            raise AgentHomeContractError("Home overlay mtime_ns must be non-negative")

    def to_json(self) -> JsonObject:
        return {
            "relative_path": self.relative_path,
            "state": self.state.value,
            "baseline_digest": self.baseline_digest,
            "runtime_digest": self.runtime_digest,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "HomeOverlayRecord":
        try:
            state = HomeOverlayState(_required_str(value, "state"))
        except ValueError as exc:
            raise AgentHomeContractError("Unknown Home overlay state") from exc
        return cls(
            relative_path=_required_str(value, "relative_path"),
            state=state,
            baseline_digest=_optional_str(value, "baseline_digest"),
            runtime_digest=_optional_str(value, "runtime_digest"),
            size=_non_negative_int(value, "size"),
            mtime_ns=_non_negative_int(value, "mtime_ns"),
        )


@dataclass(frozen=True)
class HomeOverlayManifest:
    revision: int = 0
    records: tuple[HomeOverlayRecord, ...] = field(default_factory=tuple)
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise AgentHomeContractError("Home overlay schema_version must be 2")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise AgentHomeContractError("Home overlay revision must be non-negative")
        records = tuple(self.records)
        if any(not isinstance(record, HomeOverlayRecord) for record in records):
            raise AgentHomeContractError(
                "Home overlay records must contain HomeOverlayRecord values"
            )
        object.__setattr__(self, "records", records)
        paths = tuple(record.relative_path for record in records)
        if len(paths) != len(set(paths)):
            raise AgentHomeContractError("Home overlay paths must be unique")

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "records": [record.to_json() for record in self.records],
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "HomeOverlayManifest":
        schema_version = _non_negative_int(value, "schema_version")
        if schema_version not in {1, 2}:
            raise AgentHomeContractError("Home overlay schema_version must be 1 or 2")
        if schema_version == 1:
            legacy_day = _required_str(value, "day")
            try:
                date.fromisoformat(legacy_day)
            except ValueError as exc:
                raise AgentHomeContractError(
                    "Legacy Home overlay day must be an ISO date"
                ) from exc
        records_value = value.get("records", [])
        if not isinstance(records_value, list):
            raise AgentHomeContractError("Home overlay records must be a list")
        records: list[HomeOverlayRecord] = []
        for item in records_value:
            if not isinstance(item, dict):
                raise AgentHomeContractError("Home overlay records must be objects")
            records.append(HomeOverlayRecord.from_json(to_json_object(item)))
        return cls(
            revision=_non_negative_int(value, "revision"),
            records=tuple(records),
        )

    def record_for(self, relative_path: str) -> HomeOverlayRecord | None:
        return next(
            (
                record
                for record in self.records
                if record.relative_path == relative_path
            ),
            None,
        )

    def with_record(self, record: HomeOverlayRecord) -> "HomeOverlayManifest":
        records = {existing.relative_path: existing for existing in self.records}
        records[record.relative_path] = record
        return replace(
            self,
            revision=self.revision + 1,
            records=tuple(records[path] for path in sorted(records)),
        )

    def without_record(self, relative_path: str) -> "HomeOverlayManifest":
        if self.record_for(relative_path) is None:
            return self
        return replace(
            self,
            revision=self.revision + 1,
            records=tuple(
                record
                for record in self.records
                if record.relative_path != relative_path
            ),
        )


@dataclass(frozen=True)
class EffectiveHomeResource:
    relative_path: str
    path: Path
    digest: str
    state: HomeOverlayState
    baseline_digest: str = ""


@dataclass(frozen=True)
class HomeOverlayOperation:
    operation_id: str
    relative_path: str
    before: HomeOverlayRecord | None
    after: HomeOverlayRecord

    def __post_init__(self) -> None:
        if (
            not isinstance(self.operation_id, str)
            or not self.operation_id.startswith("op_")
            or not self.operation_id.replace("_", "").isalnum()
        ):
            raise AgentHomeContractError("Home operation id is invalid")
        if self.before is not None and not isinstance(self.before, HomeOverlayRecord):
            raise AgentHomeContractError(
                "Home operation before must be a HomeOverlayRecord"
            )
        if not isinstance(self.after, HomeOverlayRecord):
            raise AgentHomeContractError(
                "Home operation after must be a HomeOverlayRecord"
            )
        _validate_relative_path(self.relative_path)
        if self.relative_path != self.after.relative_path or (
            self.before is not None and self.before.relative_path != self.relative_path
        ):
            raise AgentHomeContractError("Home operation paths do not match")

    def to_json(self) -> JsonObject:
        return {
            "schema_version": 1,
            "operation_id": self.operation_id,
            "relative_path": self.relative_path,
            "before": self.before.to_json() if self.before is not None else None,
            "after": self.after.to_json(),
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "HomeOverlayOperation":
        if _non_negative_int(value, "schema_version") != 1:
            raise AgentHomeContractError("Home operation schema_version must be 1")
        before_value = value.get("before")
        after_value = value.get("after")
        if before_value is not None and not isinstance(before_value, dict):
            raise AgentHomeContractError("Home operation before must be an object")
        if not isinstance(after_value, dict):
            raise AgentHomeContractError("Home operation after must be an object")
        operation = cls(
            operation_id=_required_str(value, "operation_id"),
            relative_path=_required_str(value, "relative_path"),
            before=(
                HomeOverlayRecord.from_json(to_json_object(before_value))
                if isinstance(before_value, dict)
                else None
            ),
            after=HomeOverlayRecord.from_json(to_json_object(after_value)),
        )
        return operation


def _validate_relative_path(value: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise AgentHomeContractError("Home overlay path must be non-empty POSIX text")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AgentHomeContractError(f"Invalid Home overlay path: {value}")
    if path.parts[0] == ".tinysoul":
        raise AgentHomeContractError(
            "Home overlay path cannot target internal metadata"
        )


def _required_str(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise AgentHomeContractError(f"Home field must be non-empty text: {name}")
    return item


def _optional_str(value: JsonObject, name: str) -> str:
    item = value.get(name, "")
    if not isinstance(item, str):
        raise AgentHomeContractError(f"Home field must be text: {name}")
    return item


def _non_negative_int(value: JsonObject, name: str) -> int:
    item = value.get(name, 0)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise AgentHomeContractError(f"Home field must be non-negative int: {name}")
    return item
