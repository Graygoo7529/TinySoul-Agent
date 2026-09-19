"""Recoverable file and directory moves with owner metadata."""

from __future__ import annotations
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from time import time
from uuid import uuid4

from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object
from tinysoul.infra.time import CalendarDay, CalendarDayError
from ..errors import WorkspaceContractError, WorkspaceIOError, WorkspaceInvariantError
from .manifest import WorkspaceResourceRecord


@dataclass(frozen=True)
class WorkspaceTrashItem:
    trash_id: str
    original: WorkspaceResourceRecord
    descendants: tuple[WorkspaceResourceRecord, ...]
    trashed_at: float
    day: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.trash_id, str)
            or len(self.trash_id) != 32
            or any(char not in "0123456789abcdef" for char in self.trash_id)
        ):
            raise WorkspaceContractError("Workspace Trash identity is invalid")
        if not isinstance(self.original, WorkspaceResourceRecord) or not isinstance(
            self.descendants, tuple
        ):
            raise WorkspaceContractError("Workspace Trash metadata is invalid")
        if (
            isinstance(self.trashed_at, bool)
            or not isinstance(self.trashed_at, (float, int))
            or not math.isfinite(self.trashed_at)
            or self.trashed_at < 0
            or not isinstance(self.day, str)
        ):
            raise WorkspaceContractError("Workspace Trash time is invalid")
        if self.day:
            try:
                CalendarDay.parse(self.day)
            except CalendarDayError as exc:
                raise WorkspaceContractError("Workspace Trash day is invalid") from exc
        prefix = self.original.relative_path + "/"
        if any(
            not isinstance(item, WorkspaceResourceRecord)
            or not item.relative_path.startswith(prefix)
            for item in self.descendants
        ):
            raise WorkspaceContractError(
                "Workspace Trash descendant is outside its resource"
            )
        if len({item.link for item in self.descendants}) != len(self.descendants):
            raise WorkspaceContractError("Workspace Trash descendants must be unique")

    @property
    def ref(self) -> str:
        return "trash:workspace/" + self.trash_id

    def to_json(self) -> JsonObject:
        return {
            "trash_id": self.trash_id,
            "original": self.original.to_json(),
            "descendants": [item.to_json() for item in self.descendants],
            "trashed_at": self.trashed_at,
            "day": self.day,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> WorkspaceTrashItem:
        if set(value) != {"trash_id", "original", "descendants", "trashed_at", "day"}:
            raise WorkspaceContractError(
                "Workspace Trash fields do not match the storage schema"
            )
        identity, original, children = (
            value.get("trash_id"),
            value.get("original"),
            value.get("descendants"),
        )
        timestamp, day = value.get("trashed_at"), value.get("day")
        if (
            not isinstance(identity, str)
            or not isinstance(original, dict)
            or not isinstance(children, list)
        ):
            raise WorkspaceContractError("Workspace Trash document is invalid")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (float, int))
            or not isinstance(day, str)
        ):
            raise WorkspaceContractError("Workspace Trash time is invalid")
        if any(not isinstance(item, dict) for item in children):
            raise WorkspaceContractError("Workspace Trash descendants must be objects")
        return cls(
            identity,
            WorkspaceResourceRecord.from_json(original),
            tuple(
                WorkspaceResourceRecord.from_json(item)
                for item in children
                if isinstance(item, dict)
            ),
            float(timestamp),
            day,
        )


class WorkspaceTrashStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def move_in(
        self,
        path: Path,
        original: WorkspaceResourceRecord,
        descendants: tuple[WorkspaceResourceRecord, ...],
        *,
        day: str,
    ) -> WorkspaceTrashItem:
        item = WorkspaceTrashItem(uuid4().hex, original, descendants, time(), day)
        directory = self.root / item.trash_id
        try:
            directory.mkdir(parents=True)
            atomic_write_text(
                directory / "metadata.json",
                json.dumps(item.to_json(), ensure_ascii=False),
            )
            os.replace(path, directory / "content")
        except OSError as exc:
            raise WorkspaceIOError(
                "Workspace resource cannot be moved to Trash"
            ) from exc
        return item

    def content_path(self, item: WorkspaceTrashItem) -> Path:
        path = self.root / item.trash_id / "content"
        if (
            path.is_symlink()
            or path.is_junction()
            or path.parent.is_symlink()
            or path.parent.is_junction()
        ):
            raise WorkspaceContractError(
                "Workspace Trash cannot contain filesystem redirects"
            )
        if not path.exists():
            raise WorkspaceContractError(
                "Workspace Trash resource is no longer available"
            )
        return path

    def load(self, ref: str) -> WorkspaceTrashItem:
        prefix = "trash:workspace/"
        if not isinstance(ref, str) or not ref.startswith(prefix):
            raise WorkspaceContractError("Workspace Trash reference is invalid")
        identity = ref[len(prefix) :]
        if len(identity) != 32 or any(
            char not in "0123456789abcdef" for char in identity
        ):
            raise WorkspaceContractError("Workspace Trash identity is invalid")
        directory = self.root / identity
        if directory.is_symlink() or directory.is_junction():
            raise WorkspaceContractError("Workspace Trash redirects are invalid")
        try:
            raw = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            if (directory / "content").exists():
                raise WorkspaceInvariantError(
                    "Workspace Trash metadata is missing"
                ) from exc
            raise WorkspaceContractError(
                "Workspace Trash reference does not exist"
            ) from exc
        except OSError as exc:
            raise WorkspaceIOError("Workspace Trash metadata cannot be read") from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise WorkspaceInvariantError(
                "Workspace Trash metadata is invalid"
            ) from exc
        try:
            if not isinstance(raw, dict):
                raise WorkspaceContractError(
                    "Workspace Trash metadata must be an object"
                )
            item = WorkspaceTrashItem.from_json(to_json_object(raw))
            if item.trash_id != identity:
                raise WorkspaceContractError("Workspace Trash identity mismatch")
        except (WorkspaceContractError, JsonTypeError) as exc:
            raise WorkspaceInvariantError(
                "Workspace Trash metadata is invalid"
            ) from exc
        self.content_path(item)
        return item

    def list(self) -> tuple[WorkspaceTrashItem, ...]:
        try:
            if not self.root.exists():
                return ()
            # A metadata-only entry represents a move which never happened or a
            # completed restore. Content presence is the fact; no commit marker.
            entries = tuple(
                path for path in self.root.iterdir() if (path / "content").exists()
            )
            return tuple(
                sorted(
                    (self.load("trash:workspace/" + path.name) for path in entries),
                    key=lambda item: item.trashed_at,
                )
            )
        except OSError as exc:
            raise WorkspaceIOError("Workspace Trash cannot be listed") from exc
