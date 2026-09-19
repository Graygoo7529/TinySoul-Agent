"""Serialized Workspace mutations and explicit committed-side-effect failures."""

from __future__ import annotations
from collections.abc import Sequence
from dataclasses import dataclass, replace
import os
from pathlib import Path
from threading import RLock

from tinysoul.infra.filesystem import atomic_write_bytes
from ..config import WorkspaceSettings
from ..errors import WorkspaceContractError, WorkspaceError, WorkspaceIOError
from ..inspection.models import WorkspaceBundleResult, WorkspaceBundleWrite
from .manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
    WorkspaceResourceRecord,
    WorkspaceResourceKind,
    WorkspaceTag,
)
from .reconcile import WorkspaceReconciler
from .trash import WorkspaceTrashItem, WorkspaceTrashStore


@dataclass(frozen=True)
class WorkspaceTextEdit:
    old_text: str
    new_text: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.old_text, str)
            or not self.old_text
            or not isinstance(self.new_text, str)
        ):
            raise WorkspaceContractError(
                "Workspace edit requires non-empty old_text and text new_text"
            )


class WorkspaceMutations:
    """One owner lock covers file changes, metadata and publication inputs."""

    def __init__(
        self,
        *,
        settings: WorkspaceSettings,
        store: WorkspaceManifestStore,
        discovery: WorkspaceReconciler,
        trash: WorkspaceTrashStore,
        lock: RLock,
    ) -> None:
        self._settings, self._store, self._discovery = settings, store, discovery
        self._trash, self._lock = trash, lock

    def write_bundle(
        self,
        writes: Sequence[WorkspaceBundleWrite],
        *,
        delete_links: Sequence[str] = (),
    ) -> WorkspaceBundleResult:
        items = tuple(writes)
        if not items or any(
            not isinstance(item, WorkspaceBundleWrite) for item in items
        ):
            raise WorkspaceContractError("Workspace bundle requires typed writes")
        if len({item.link for item in items}) != len(items):
            raise WorkspaceContractError("Workspace bundle targets must be unique")
        with self._lock:
            deletes = tuple(delete_links)
            if len(set(deletes)) != len(deletes) or set(deletes) & {
                item.link for item in items
            }:
                raise WorkspaceContractError(
                    "Workspace bundle delete targets must be unique and separate"
                )
            for link in deletes:
                record = self._discovery.inspect_record(self._discovery.path_for(link))
                if record.kind is WorkspaceResourceKind.DIRECTORY:
                    raise WorkspaceContractError(
                        "Workspace bundle deletion accepts files only"
                    )
            paths: list[Path] = []
            for item in items:
                path = self._discovery.path_for(item.link)
                if path.exists() and (not path.is_file() or not item.overwrite):
                    raise WorkspaceContractError(
                        "Workspace target already exists or is not a file"
                    )
                if any(
                    parent.exists() and not parent.is_dir() for parent in path.parents
                ):
                    raise WorkspaceContractError(
                        "Workspace target parent is not a directory"
                    )
                paths.append(path)
            if any(
                first in second.parents or second in first.parents
                for index, first in enumerate(paths)
                for second in paths[index + 1 :]
            ):
                raise WorkspaceContractError(
                    "Workspace bundle targets cannot contain one another"
                )
            committed: list[str] = []
            try:
                for item, path in zip(items, paths, strict=True):
                    atomic_write_bytes(path, item.data)
                    committed.append(item.link)
                for link in deletes:
                    self.trash_resource(link)
                    committed.append(link)
            except OSError as exc:
                raise WorkspaceIOError(
                    "Workspace bundle could not finish writing",
                    committed_links=tuple(committed),
                ) from exc
            except WorkspaceError as exc:
                raise WorkspaceIOError(
                    "Workspace bundle could not finish its changes",
                    committed_links=tuple(committed),
                ) from exc
            manifest = self._index_after(tuple(committed))
            by_link = {record.link: record for record in manifest.resources}
            return WorkspaceBundleResult(
                manifest, tuple(by_link[item.link] for item in items)
            )

    def write_text(
        self, link: str, text: str, *, overwrite: bool = False
    ) -> WorkspaceResourceRecord:
        self._validate_text(text)
        return self.write_bundle(
            (WorkspaceBundleWrite(link, text.encode("utf-8"), overwrite),)
        ).records[0]

    def append_text(self, link: str, text: str) -> WorkspaceResourceRecord:
        self._validate_text(text)
        with self._lock:
            original = self._editable_text(link)
            return self.write_text(link, original + text, overwrite=True)

    def edit_text(
        self, link: str, edits: Sequence[WorkspaceTextEdit]
    ) -> WorkspaceResourceRecord:
        items = tuple(edits)
        if not items or any(not isinstance(item, WorkspaceTextEdit) for item in items):
            raise WorkspaceContractError("Workspace edit requires typed replacements")
        with self._lock:
            updated = self._editable_text(link)
            # Every replacement is validated before the single file commit.
            for item in items:
                first = updated.find(item.old_text)
                if first < 0 or updated.find(item.old_text, first + 1) >= 0:
                    raise WorkspaceContractError(
                        "Workspace edit old_text must match exactly once"
                    )
                updated = updated.replace(item.old_text, item.new_text, 1)
            return self.write_text(link, updated, overwrite=True)

    def mkdir(self, link: str) -> WorkspaceResourceRecord:
        with self._lock:
            path = self._discovery.path_for(link)
            if path.exists():
                raise WorkspaceContractError(
                    "Workspace directory target already exists"
                )
            try:
                path.mkdir(parents=True)
            except OSError as exc:
                raise WorkspaceIOError("Workspace directory cannot be created") from exc
            manifest = self._index_after((link,))
            return next(record for record in manifest.resources if record.link == link)

    def move(self, link: str, target_link: str) -> WorkspaceResourceRecord:
        with self._lock:
            source, target = self._discovery.path_for(link), self._discovery.path_for(
                target_link
            )
            if (
                not source.exists()
                or target.exists()
                or source == target
                or source in target.parents
            ):
                raise WorkspaceContractError(
                    "Workspace move source or target is invalid"
                )
            current = self._store.load()
            changed_metadata = tuple(
                replace(
                    record,
                    link=target_link + record.link[len(link) :],
                    relative_path=target.relative_to(
                        self._settings.root.resolve()
                    ).as_posix()
                    + record.relative_path[
                        len(
                            source.relative_to(self._settings.root.resolve()).as_posix()
                        ) :
                    ],
                )
                for record in current.resources
                if record.link == link or record.link.startswith(link + "/")
            )
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
            except OSError as exc:
                raise WorkspaceIOError("Workspace resource cannot be moved") from exc
            manifest = self._index_after((link, target_link), metadata=changed_metadata)
            return next(
                record for record in manifest.resources if record.link == target_link
            )

    def tag(self, link: str, tags: tuple[WorkspaceTag, ...]) -> WorkspaceResourceRecord:
        return self._metadata(link, tags=tags)

    def set_description(self, link: str, description: str) -> WorkspaceResourceRecord:
        if not isinstance(description, str) or len(description) > 2000:
            raise WorkspaceContractError("Workspace description exceeds its bound")
        return self._metadata(link, description=description.strip())

    def trash_resource(self, link: str) -> WorkspaceTrashItem:
        with self._lock:
            current = self._store.load()
            previous = next(
                (record for record in current.resources if record.link == link), None
            )
            path = self._discovery.path_for(link)
            original = self._discovery.inspect_record(path, previous)
            children = tuple(
                record
                for record in current.resources
                if record.link.startswith(link + "/")
            )
            item = self._trash.move_in(path, original, children, day=current.day)
            self._index_after((link,))
            return item

    def restore_resource(self, ref: str) -> WorkspaceResourceRecord:
        with self._lock:
            item = self._trash.load(ref)
            if item.day != self._store.load().day:
                raise WorkspaceContractError("Workspace Trash belongs to another day")
            target = self._discovery.path_for(item.original.link)
            if target.exists():
                raise WorkspaceContractError("Workspace restore target already exists")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(self._trash.content_path(item), target)
            except OSError as exc:
                raise WorkspaceIOError(
                    "Workspace Trash resource cannot be restored"
                ) from exc
            manifest = self._index_after(
                (item.original.link,), metadata=(item.original, *item.descendants)
            )
            return next(
                record
                for record in manifest.resources
                if record.link == item.original.link
            )

    def _metadata(
        self,
        link: str,
        *,
        description: str | None = None,
        tags: tuple[WorkspaceTag, ...] | None = None,
    ) -> WorkspaceResourceRecord:
        with self._lock:
            current = self._store.load()
            previous = next(
                (record for record in current.resources if record.link == link), None
            )
            record = self._discovery.inspect_record(
                self._discovery.path_for(link), previous
            )
            record = replace(
                record,
                description=record.description if description is None else description,
                tags=record.tags if tags is None else tags,
            )
            resources = tuple(
                sorted(
                    (
                        *[item for item in current.resources if item.link != link],
                        record,
                    ),
                    key=lambda item: item.link,
                )
            )
            self._store.save(replace(current, resources=resources))
            return record

    def _editable_text(self, link: str) -> str:
        path = self._discovery.path_for(link)
        record = self._discovery.inspect_record(path)
        if record.kind is not WorkspaceResourceKind.TEXT:
            raise WorkspaceContractError("Workspace edit target must be text")
        try:
            with path.open(encoding="utf-8") as stream:
                text = stream.read(self._settings.max_write_chars + 1)
        except UnicodeError as exc:
            raise WorkspaceContractError("Workspace edit target is not UTF-8") from exc
        except OSError as exc:
            raise WorkspaceIOError("Workspace edit target cannot be read") from exc
        self._validate_text(text)
        return text

    def _validate_text(self, text: str) -> None:
        if not isinstance(text, str) or len(text) > self._settings.max_write_chars:
            raise WorkspaceContractError("Workspace write requires bounded text")
        try:
            text.encode("utf-8")
        except UnicodeError as exc:
            raise WorkspaceContractError("Workspace write must be valid UTF-8") from exc

    def _index_after(
        self,
        committed: tuple[str, ...],
        *,
        metadata: tuple[WorkspaceResourceRecord, ...] = (),
    ) -> WorkspaceManifest:
        try:
            result = self._discovery.reconcile(metadata=metadata)
            if not result.complete:
                raise WorkspaceIOError("Workspace index discovery was incomplete")
            return result.manifest
        except WorkspaceError as exc:
            raise WorkspaceIOError(
                "Workspace files changed but index update failed",
                committed_links=committed,
            ) from exc
