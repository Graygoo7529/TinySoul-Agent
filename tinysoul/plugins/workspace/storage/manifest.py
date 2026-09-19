"""Workspace resource metadata. File bodies remain the content authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path

from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object
from tinysoul.infra.time import CalendarDay, CalendarDayError
from ..errors import WorkspaceContractError, WorkspaceIOError, WorkspaceInvariantError
from ..links import WorkspaceLink


class WorkspaceResourceKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"
    BINARY = "binary"
    DIRECTORY = "directory"


class WorkspaceTag(StrEnum):
    PINNED = "pinned"
    TMP = "tmp"
    LIBRARY = "library"


@dataclass(frozen=True)
class WorkspaceResourceRecord:
    link: str
    relative_path: str
    kind: WorkspaceResourceKind
    media_type: str
    suffix: str
    summary: str
    size: int
    mtime_ns: int
    description: str = ""
    tags: tuple[WorkspaceTag, ...] = ()

    def __post_init__(self) -> None:
        if WorkspaceLink.parse(self.link).relative_path != self.relative_path:
            raise WorkspaceContractError(
                "Workspace record identity disagrees with its path"
            )
        if not isinstance(self.kind, WorkspaceResourceKind):
            raise WorkspaceContractError("Workspace record kind is invalid")
        for name in ("media_type", "summary"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise WorkspaceContractError("Workspace record text is invalid")
        if not isinstance(self.suffix, str) or not isinstance(self.description, str):
            raise WorkspaceContractError("Workspace record metadata is invalid")
        if len(self.description) > 2000:
            raise WorkspaceContractError("Workspace description exceeds its bound")
        for value in (self.size, self.mtime_ns):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise WorkspaceContractError(
                    "Workspace file metadata must be non-negative integers"
                )
        if not isinstance(self.tags, tuple) or any(
            not isinstance(tag, WorkspaceTag) for tag in self.tags
        ):
            raise WorkspaceContractError("Workspace tags must be typed values")
        if len(set(self.tags)) != len(self.tags):
            raise WorkspaceContractError("Workspace tags must be unique")

    @property
    def context_summary(self) -> str:
        return ". ".join(
            part
            for part in (self.summary, self.description, ", ".join(self.tags))
            if part
        )

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
            "description": self.description,
            "tags": [tag.value for tag in self.tags],
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> WorkspaceResourceRecord:
        expected = {
            "link",
            "relative_path",
            "kind",
            "media_type",
            "suffix",
            "summary",
            "size",
            "mtime_ns",
            "description",
            "tags",
        }
        if set(value) != expected:
            raise WorkspaceContractError(
                "Workspace resource fields do not match the storage schema"
            )
        tags = value["tags"]
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise WorkspaceContractError("Workspace tags must be a string list")
        try:
            typed_tags = tuple(
                WorkspaceTag(tag) for tag in tags if isinstance(tag, str)
            )
            kind = WorkspaceResourceKind(_text(value, "kind"))
        except ValueError as exc:
            raise WorkspaceContractError(
                "Workspace resource kind or tag is unknown"
            ) from exc
        return cls(
            link=_text(value, "link"),
            relative_path=_text(value, "relative_path"),
            kind=kind,
            media_type=_text(value, "media_type"),
            suffix=_text(value, "suffix"),
            summary=_text(value, "summary"),
            size=_integer(value, "size"),
            mtime_ns=_integer(value, "mtime_ns"),
            description=_text(value, "description"),
            tags=typed_tags,
        )


@dataclass(frozen=True)
class WorkspaceManifest:
    day: str = ""
    resources: tuple[WorkspaceResourceRecord, ...] = ()
    schema_version: int = 4

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 4:
            raise WorkspaceContractError("Workspace manifest schema_version must be 4")
        if not isinstance(self.day, str):
            raise WorkspaceContractError("Workspace day must be text")
        if self.day:
            try:
                CalendarDay.parse(self.day)
            except CalendarDayError as exc:
                raise WorkspaceContractError("Workspace day is invalid") from exc
        if not isinstance(self.resources, tuple) or any(
            not isinstance(item, WorkspaceResourceRecord) for item in self.resources
        ):
            raise WorkspaceContractError("Workspace manifest requires resource records")
        links = [item.link for item in self.resources]
        if len(set(links)) != len(links):
            raise WorkspaceContractError(
                "Workspace manifest resource identities must be unique"
            )

    def to_json(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "day": self.day,
            "resources": [item.to_json() for item in self.resources],
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> WorkspaceManifest:
        if set(value) != {"schema_version", "day", "resources"}:
            raise WorkspaceContractError(
                "Workspace manifest fields do not match the storage schema"
            )
        resources = value["resources"]
        if not isinstance(resources, list) or any(
            not isinstance(item, dict) for item in resources
        ):
            raise WorkspaceContractError("Workspace manifest resources must be objects")
        return cls(
            day=_text(value, "day"),
            schema_version=_integer(value, "schema_version"),
            resources=tuple(
                WorkspaceResourceRecord.from_json(item)
                for item in resources
                if isinstance(item, dict)
            ),
        )


class WorkspaceManifestStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> WorkspaceManifest:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return WorkspaceManifest()
        except UnicodeError as exc:
            raise WorkspaceInvariantError(
                "Workspace index encoding is invalid"
            ) from exc
        except OSError as exc:
            raise WorkspaceIOError("Workspace index cannot be read") from exc
        try:
            raw = json.loads(text)
            if not isinstance(raw, dict):
                raise WorkspaceContractError("Workspace index must be an object")
            return WorkspaceManifest.from_json(to_json_object(raw))
        except (
            json.JSONDecodeError,
            UnicodeError,
            WorkspaceContractError,
            JsonTypeError,
        ) as exc:
            raise WorkspaceInvariantError(
                "Workspace index schema or encoding is invalid"
            ) from exc

    def save(self, manifest: WorkspaceManifest) -> None:
        try:
            atomic_write_text(
                self.path,
                json.dumps(manifest.to_json(), ensure_ascii=False, indent=2) + "\n",
            )
        except OSError as exc:
            raise WorkspaceIOError("Workspace index cannot be written") from exc


def _text(value: JsonObject, name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str):
        raise WorkspaceContractError("Workspace metadata field must be text")
    return item


def _integer(value: JsonObject, name: str) -> int:
    item = value.get(name)
    if isinstance(item, bool) or not isinstance(item, int):
        raise WorkspaceContractError("Workspace metadata field must be an integer")
    return item
