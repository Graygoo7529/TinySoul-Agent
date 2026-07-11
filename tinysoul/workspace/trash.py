"""Recoverable Workspace trash storage."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
from time import time
from uuid import uuid4

from tinysoul.infra.filesystem import (
    FilesystemBoundaryError,
    atomic_write_text,
    resolve_under_root,
)
from tinysoul.infra.json import JsonObject, to_json_object

from .errors import WorkspaceContractError, WorkspaceIOError
from .manifest import WorkspaceResourceRecord


TRASH_REF_PREFIX = "trash:workspace/"


@dataclass(frozen=True)
class WorkspaceTrashItem:
    """One recoverable resource outside the active Workspace root."""

    trash_id: str
    original: WorkspaceResourceRecord
    trashed_at: float
    reason: str
    source_turn_id: str = ""

    @property
    def ref(self) -> str:
        return f"{TRASH_REF_PREFIX}{self.trash_id}"

    def to_json(self) -> JsonObject:
        return {
            "trash_id": self.trash_id,
            "original": self.original.to_json(),
            "trashed_at": self.trashed_at,
            "reason": self.reason,
            "source_turn_id": self.source_turn_id,
        }

    @classmethod
    def from_json(cls, value: JsonObject) -> "WorkspaceTrashItem":
        trash_id = value.get("trash_id")
        original = value.get("original")
        trashed_at = value.get("trashed_at")
        reason = value.get("reason")
        source_turn_id = value.get("source_turn_id", "")
        if not isinstance(trash_id, str) or not trash_id:
            raise WorkspaceContractError("Trash item requires a non-empty trash_id")
        if not isinstance(original, dict):
            raise WorkspaceContractError("Trash item requires an original record")
        if isinstance(trashed_at, bool) or not isinstance(trashed_at, (int, float)):
            raise WorkspaceContractError("Trash item trashed_at must be numeric")
        if not isinstance(reason, str) or not reason:
            raise WorkspaceContractError("Trash item requires a non-empty reason")
        if not isinstance(source_turn_id, str):
            raise WorkspaceContractError("Trash item source_turn_id must be a string")
        return cls(
            trash_id=trash_id,
            original=WorkspaceResourceRecord.from_json(to_json_object(original)),
            trashed_at=float(trashed_at),
            reason=reason,
            source_turn_id=source_turn_id,
        )


class WorkspaceTrashStore:
    """Crash-recoverable directory store for logically deleted resources."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def prepare(
        self,
        record: WorkspaceResourceRecord,
        *,
        reason: str,
        source_turn_id: str = "",
    ) -> WorkspaceTrashItem:
        if not reason:
            raise WorkspaceContractError("Workspace trash reason must be non-empty")
        item = WorkspaceTrashItem(
            trash_id=f"trash_{uuid4().hex[:12]}",
            original=record,
            trashed_at=time(),
            reason=reason,
            source_turn_id=source_turn_id,
        )
        directory = self._directory(item.trash_id)
        try:
            directory.mkdir(parents=True, exist_ok=False)
            atomic_write_text(
                directory / "record.json",
                json.dumps(item.to_json(), ensure_ascii=False, sort_keys=True, indent=2)
                + "\n",
            )
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to prepare Workspace trash item: {exc}") from exc
        return item

    def content_path(self, item: WorkspaceTrashItem) -> Path:
        return self._directory(item.trash_id) / "content"

    def commit(self, item: WorkspaceTrashItem) -> None:
        content = self.content_path(item)
        if not content.is_file():
            raise WorkspaceIOError("Workspace trash item has no staged content")
        try:
            atomic_write_text(self._directory(item.trash_id) / "COMMITTED", "\n")
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to commit Workspace trash item: {exc}") from exc

    def load(self, ref: str) -> WorkspaceTrashItem:
        trash_id = _trash_id(ref)
        directory = self._directory(trash_id)
        if not (directory / "COMMITTED").is_file():
            raise WorkspaceContractError(f"Unknown committed Workspace trash ref: {ref}")
        return self._load_directory(directory)

    def list(self) -> tuple[WorkspaceTrashItem, ...]:
        if not self._root.exists():
            return ()
        items: list[WorkspaceTrashItem] = []
        for directory in sorted(self._root.iterdir(), key=lambda path: path.name):
            if directory.is_dir() and (directory / "COMMITTED").is_file():
                items.append(self._load_directory(directory))
        return tuple(items)

    def discard(self, item: WorkspaceTrashItem) -> None:
        try:
            shutil.rmtree(self._directory(item.trash_id))
        except FileNotFoundError:
            return
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to remove Workspace trash item: {exc}") from exc

    def recover_uncommitted(self, active_root: Path) -> int:
        if not self._root.exists():
            return 0
        recovered = 0
        for directory in sorted(self._root.iterdir(), key=lambda path: path.name):
            if not directory.is_dir() or (directory / "COMMITTED").exists():
                continue
            item = self._load_directory(directory)
            content = directory / "content"
            if content.exists():
                try:
                    target = resolve_under_root(
                        active_root,
                        item.original.relative_path,
                    )
                except FilesystemBoundaryError as exc:
                    raise WorkspaceIOError(str(exc)) from exc
                if target.exists():
                    raise WorkspaceIOError(
                        "Cannot recover prepared Workspace trash item because the "
                        f"original path exists: {item.original.relative_path}"
                    )
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(content, target)
                except OSError as exc:
                    raise WorkspaceIOError(
                        f"Failed to recover prepared Workspace trash item: {exc}"
                    ) from exc
                recovered += 1
            self.discard(item)
        return recovered

    def _load_directory(self, directory: Path) -> WorkspaceTrashItem:
        try:
            value = json.loads((directory / "record.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceIOError(f"Failed to load Workspace trash item: {exc}") from exc
        if not isinstance(value, dict):
            raise WorkspaceContractError("Workspace trash record root must be an object")
        item = WorkspaceTrashItem.from_json(to_json_object(value))
        if item.trash_id != directory.name:
            raise WorkspaceContractError(
                "Workspace trash directory does not match its record id"
            )
        return item

    def _directory(self, trash_id: str) -> Path:
        try:
            return resolve_under_root(self._root, trash_id)
        except FilesystemBoundaryError as exc:
            raise WorkspaceContractError(str(exc)) from exc


def _trash_id(ref: str) -> str:
    if not isinstance(ref, str) or not ref.startswith(TRASH_REF_PREFIX):
        raise WorkspaceContractError(f"Invalid Workspace trash ref: {ref}")
    trash_id = ref[len(TRASH_REF_PREFIX) :]
    if not trash_id or "/" in trash_id or "\\" in trash_id:
        raise WorkspaceContractError(f"Invalid Workspace trash ref: {ref}")
    return trash_id
