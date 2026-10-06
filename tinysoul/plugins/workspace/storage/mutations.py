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
        delete_refs: Sequence[str] = (),
    ) -> WorkspaceBundleResult:
        items = tuple(writes)
        if not items or any(
            not isinstance(item, WorkspaceBundleWrite) for item in items
        ):
            raise WorkspaceContractError("Workspace bundle requires typed writes")
        with self._lock:
            deletes = tuple(delete_refs)
            paths = tuple(self._discovery.path_for(item.ref) for item in items)
            delete_paths = tuple(self._discovery.path_for(ref) for ref in deletes)
            targets = (*paths, *delete_paths)
            if len(set(targets)) != len(targets):
                raise WorkspaceContractError(
                    "Workspace bundle targets must be unique and separate"
                )
            for path in delete_paths:
                record = self._discovery.inspect_record(path)
                if record.kind is WorkspaceResourceKind.DIRECTORY:
                    raise WorkspaceContractError(
                        "Workspace bundle deletion accepts files only"
                    )
            for item, path in zip(items, paths, strict=True):
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
            if any(
                first in second.parents or second in first.parents
                for index, first in enumerate(targets)
                for second in targets[index + 1 :]
            ):
                raise WorkspaceContractError(
                    "Workspace bundle targets cannot contain one another"
                )
            committed: list[str] = []
            try:
                for item, path in zip(items, paths, strict=True):
                    atomic_write_bytes(path, item.data)
                    committed.append(item.ref)
                for ref in deletes:
                    self.trash_resource(ref)
                    committed.append(ref)
            except OSError as exc:
                raise WorkspaceIOError(
                    "Workspace bundle could not finish writing",
                    committed_refs=tuple(committed),
                ) from exc
            except WorkspaceError as exc:
                nested = exc.committed_refs if isinstance(exc, WorkspaceIOError) else ()
                raise WorkspaceIOError(
                    "Workspace bundle could not finish its changes",
                    committed_refs=tuple(dict.fromkeys((*committed, *nested))),
                ) from exc
            manifest = self._index_after(tuple(committed))
            by_path = {
                self._settings.root.resolve() / record.relative_path: record
                for record in manifest.resources
            }
            return WorkspaceBundleResult(
                manifest, tuple(by_path[path] for path in paths)
            )

    def write_text(
        self, ref: str, text: str, *, overwrite: bool = False
    ) -> WorkspaceResourceRecord:
        self._validate_text(text)
        return self.write_bundle(
            (WorkspaceBundleWrite(ref, text.encode("utf-8"), overwrite),)
        ).records[0]

    def append_text(self, ref: str, text: str) -> WorkspaceResourceRecord:
        self._validate_text(text)
        with self._lock:
            original = self._editable_text(ref)
            return self.write_text(ref, original + text, overwrite=True)

    def edit_text(
        self, ref: str, edits: Sequence[WorkspaceTextEdit]
    ) -> WorkspaceResourceRecord:
        items = tuple(edits)
        if not items or any(not isinstance(item, WorkspaceTextEdit) for item in items):
            raise WorkspaceContractError("Workspace edit requires typed replacements")
        with self._lock:
            updated = self._editable_text(ref)
            # Every replacement is validated before the single file commit.
            for item in items:
                first = updated.find(item.old_text)
                if first < 0 or updated.find(item.old_text, first + 1) >= 0:
                    raise WorkspaceContractError(
                        "Workspace edit old_text must match exactly once"
                    )
                updated = updated.replace(item.old_text, item.new_text, 1)
            return self.write_text(ref, updated, overwrite=True)

    def mkdir(self, ref: str) -> WorkspaceResourceRecord:
        with self._lock:
            path = self._discovery.path_for(ref)
            if path.exists():
                raise WorkspaceContractError(
                    "Workspace directory target already exists"
                )
            try:
                path.mkdir(parents=True)
            except OSError as exc:
                raise WorkspaceIOError("Workspace directory cannot be created") from exc
            manifest = self._index_after((ref,))
            return next(record for record in manifest.resources if record.ref == ref)

    def move(self, ref: str, target_ref: str) -> WorkspaceResourceRecord:
        with self._lock:
            source, target = (
                self._discovery.path_for(ref),
                self._discovery.path_for(target_ref),
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
            root = self._settings.root.resolve()
            source_relative = source.relative_to(root).as_posix()
            target_relative = target.relative_to(root).as_posix()
            ref = "workspace:" + source_relative
            target_ref = "workspace:" + target_relative
            changed_metadata = tuple(
                replace(
                    record,
                    ref=target_ref + record.ref[len(ref) :],
                    relative_path=target_relative
                    + record.relative_path[len(source_relative) :],
                )
                for record in current.resources
                if record.ref == ref or record.ref.startswith(ref + "/")
            )
            manifest = self._relocate(
                source, target, current, changed_metadata, (ref, target_ref)
            )
            return next(
                record for record in manifest.resources if record.ref == target_ref
            )

    def tag(self, ref: str, tags: tuple[WorkspaceTag, ...]) -> WorkspaceResourceRecord:
        return self._metadata(ref, tags=tags)

    def set_description(self, ref: str, description: str) -> WorkspaceResourceRecord:
        if not isinstance(description, str) or len(description) > 2000:
            raise WorkspaceContractError("Workspace description exceeds its bound")
        return self._metadata(ref, description=description.strip())

    def trash_resource(self, ref: str) -> WorkspaceTrashItem:
        with self._lock:
            current = self._store.load()
            previous = next(
                (record for record in current.resources if record.ref == ref), None
            )
            path = self._discovery.path_for(ref)
            original = self._discovery.inspect_record(path, previous)
            children = tuple(
                record
                for record in current.resources
                if record.ref.startswith(ref + "/")
            )
            item = self._trash.move_in(path, original, children, day=current.day)
            self._index_after((ref,))
            return item

    def restore_resource(self, ref: str) -> WorkspaceResourceRecord:
        with self._lock:
            item = self._trash.load(ref)
            current = self._store.load()
            if item.day != current.day:
                raise WorkspaceContractError("Workspace Trash belongs to another day")
            target = self._discovery.path_for(item.original.ref)
            if target.exists():
                raise WorkspaceContractError("Workspace restore target already exists")
            manifest = self._relocate(
                self._trash.content_path(item),
                target,
                current,
                (item.original, *item.descendants),
                (item.original.ref,),
            )
            return next(
                record
                for record in manifest.resources
                if record.ref == item.original.ref
            )

    def _relocate(
        self,
        source: Path,
        target: Path,
        current: WorkspaceManifest,
        metadata: tuple[WorkspaceResourceRecord, ...],
        committed: tuple[str, ...],
    ) -> WorkspaceManifest:
        # Persist destination metadata before moving content. The ordinary disk
        # scan then retains whichever location exists, even after a fresh open.
        records = {record.ref: record for record in current.resources}
        records.update((record.ref, record) for record in metadata)
        self._store.save(
            replace(
                current,
                resources=tuple(sorted(records.values(), key=lambda item: item.ref)),
            )
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        except OSError as exc:
            raise WorkspaceIOError("Workspace resource cannot be moved") from exc
        return self._index_after(committed)

    def _metadata(
        self,
        ref: str,
        *,
        description: str | None = None,
        tags: tuple[WorkspaceTag, ...] | None = None,
    ) -> WorkspaceResourceRecord:
        with self._lock:
            current = self._store.load()
            previous = next(
                (record for record in current.resources if record.ref == ref), None
            )
            record = self._discovery.inspect_record(
                self._discovery.path_for(ref), previous
            )
            record = replace(
                record,
                description=record.description if description is None else description,
                tags=record.tags if tags is None else tags,
            )
            resources = tuple(
                sorted(
                    (
                        *[item for item in current.resources if item.ref != ref],
                        record,
                    ),
                    key=lambda item: item.ref,
                )
            )
            self._store.save(replace(current, resources=resources))
            return record

    def _editable_text(self, ref: str) -> str:
        path = self._discovery.path_for(ref)
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
    ) -> WorkspaceManifest:
        try:
            result = self._discovery.reconcile()
            if not result.complete:
                raise WorkspaceIOError("Workspace index discovery was incomplete")
            return result.manifest
        except WorkspaceError as exc:
            raise WorkspaceIOError(
                "Workspace files changed but index update failed",
                committed_refs=committed,
            ) from exc
