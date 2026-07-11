"""Workspace manifest models and storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from pathlib import Path

from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.infra.json import JsonObject, to_json_object

from .errors import WorkspaceContractError, WorkspaceIOError


class WorkspaceResourceKind(StrEnum):
    """Kinds of workspace resources."""

    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"
    BINARY = "binary"


class WorkspaceRetention(StrEnum):
    """How long an active Workspace resource should normally be retained."""

    EPHEMERAL = "ephemeral"
    TURN = "turn"
    DAY = "day"
    PERSISTENT = "persistent"


@dataclass(frozen=True)
class WorkspaceResourceRecord:
    """One resource entry in a workspace manifest."""

    link: str
    relative_path: str
    kind: WorkspaceResourceKind
    media_type: str
    suffix: str
    summary: str
    size: int
    mtime_ns: int
    digest: str = ""
    description: str = ""
    described_digest: str = ""
    retention: WorkspaceRetention = WorkspaceRetention.DAY
    owner_turn_id: str = ""

    def __post_init__(self) -> None:
        if not self.link:
            raise WorkspaceContractError("WorkspaceResourceRecord.link must be non-empty")
        if not self.relative_path:
            raise WorkspaceContractError(
                "WorkspaceResourceRecord.relative_path must be non-empty"
            )
        if not isinstance(self.kind, WorkspaceResourceKind):
            raise WorkspaceContractError(
                "WorkspaceResourceRecord.kind must be a WorkspaceResourceKind"
            )
        if not self.media_type:
            raise WorkspaceContractError(
                "WorkspaceResourceRecord.media_type must be non-empty"
            )
        if not isinstance(self.suffix, str):
            raise WorkspaceContractError(
                "WorkspaceResourceRecord.suffix must be a string"
            )
        if not self.summary:
            raise WorkspaceContractError(
                "WorkspaceResourceRecord.summary must be non-empty"
            )
        if self.size < 0:
            raise WorkspaceContractError("WorkspaceResourceRecord.size cannot be negative")
        if self.mtime_ns < 0:
            raise WorkspaceContractError(
                "WorkspaceResourceRecord.mtime_ns cannot be negative"
            )
        if bool(self.description) != bool(self.described_digest):
            raise WorkspaceContractError(
                "Workspace resource description and described_digest must be set together"
            )
        if self.described_digest and self.described_digest != self.digest:
            raise WorkspaceContractError(
                "Workspace resource description must match the current digest"
            )
        if not isinstance(self.retention, WorkspaceRetention):
            raise WorkspaceContractError(
                "Workspace resource retention must be a WorkspaceRetention"
            )

    @property
    def context_summary(self) -> str:
        if not self.description:
            return self.summary
        return f"{self.summary}. {self.description}"

    def to_json(self) -> JsonObject:
        return {
            "link": self.link,
            "relative_path": self.relative_path,
            "kind": self.kind.value,
            "media_type": self.media_type,
            "suffix": self.suffix,
            "summary": self.summary,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "digest": self.digest,
            "description": self.description,
            "described_digest": self.described_digest,
            "retention": self.retention.value,
            "owner_turn_id": self.owner_turn_id,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "WorkspaceResourceRecord":
        try:
            kind = WorkspaceResourceKind(_required_str(value, "kind"))
        except ValueError as exc:
            raise WorkspaceContractError("Unknown workspace resource kind") from exc
        retention_value = _optional_str(value, "retention") or WorkspaceRetention.DAY.value
        try:
            retention = WorkspaceRetention(retention_value)
        except ValueError as exc:
            raise WorkspaceContractError(
                f"Unknown Workspace resource retention: {retention_value}"
            ) from exc
        return cls(
            link=_required_str(value, "link"),
            relative_path=_required_str(value, "relative_path"),
            kind=kind,
            media_type=_required_str(value, "media_type"),
            suffix=_optional_str(value, "suffix"),
            summary=_required_str(value, "summary"),
            size=_required_int(value, "size"),
            mtime_ns=_required_int(value, "mtime_ns"),
            digest=_optional_str(value, "digest"),
            description=_optional_str(value, "description"),
            described_digest=_optional_str(value, "described_digest"),
            retention=retention,
            owner_turn_id=_optional_str(value, "owner_turn_id"),
        )


@dataclass(frozen=True)
class WorkspaceManifest:
    """Current workspace resource index."""

    schema_version: int = 2
    revision: int = 0
    resources: tuple[WorkspaceResourceRecord, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 2
        ):
            raise WorkspaceContractError(
                "Workspace manifest schema_version must be 2"
            )
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise WorkspaceContractError(
                "Workspace manifest revision must be a non-negative integer"
            )
        links = tuple(resource.link for resource in self.resources)
        if len(set(links)) != len(links):
            raise WorkspaceContractError(
                "Workspace manifest resources must contain unique links"
            )

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "resources": [resource.to_json() for resource in self.resources],
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "WorkspaceManifest":
        raw_resources = value.get("resources", [])
        if not isinstance(raw_resources, list):
            raise WorkspaceContractError("Workspace manifest resources must be a list")
        resources: list[WorkspaceResourceRecord] = []
        for item in raw_resources:
            if not isinstance(item, dict):
                raise WorkspaceContractError(
                    "Workspace manifest resources must contain objects"
                )
            resources.append(WorkspaceResourceRecord.from_json(to_json_object(item)))
        return cls(
            schema_version=_schema_version(value),
            revision=_optional_non_negative_int(value, "revision"),
            resources=tuple(resources),
        )


class WorkspaceManifestStore:
    """Read and write the workspace manifest file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> WorkspaceManifest:
        if not self._path.exists():
            return WorkspaceManifest()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceIOError(f"Failed to read workspace manifest: {exc}") from exc
        if not isinstance(raw, dict):
            raise WorkspaceContractError("Workspace manifest root must be an object")
        return WorkspaceManifest.from_json(to_json_object(raw))

    def save(self, manifest: WorkspaceManifest) -> None:
        try:
            atomic_write_text(
                self._path,
                json.dumps(
                    manifest.to_json(),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
            )
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to write workspace manifest: {exc}") from exc


def _required_str(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise WorkspaceContractError(f"Manifest field must be a non-empty string: {name}")
    return item


def _optional_str(value: JsonObject, name: str) -> str:
    item = value.get(name, "")
    if not isinstance(item, str):
        raise WorkspaceContractError(f"Manifest field must be a string: {name}")
    return item


def _required_int(value: JsonObject, name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int):
        raise WorkspaceContractError(f"Manifest field must be an integer: {name}")
    return item


def _optional_non_negative_int(value: JsonObject, name: str) -> int:
    item = value.get(name, 0)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise WorkspaceContractError(
            f"Manifest field must be a non-negative integer: {name}"
        )
    return item


def _schema_version(value: JsonObject) -> int:
    item = value.get("schema_version", 1)
    if isinstance(item, bool) or not isinstance(item, int) or item not in {1, 2}:
        raise WorkspaceContractError("Workspace manifest schema_version must be 1 or 2")
    return 2
