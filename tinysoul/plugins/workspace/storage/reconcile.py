"""Bounded disk discovery without content versions or commit guards."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
import os

from tinysoul.infra.filesystem import FilesystemBoundaryError, resolve_under_root
from ..config import WorkspaceSettings
from ..errors import WorkspaceContractError, WorkspaceIOError
from ..links import WorkspaceLink
from .manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
)
from ..inspection.classification import WorkspaceResourceClassifier


class WorkspaceDiscoverySkipKind(StrEnum):
    """Stable reasons why disk discovery omitted a resource."""

    INTERNAL = "internal"
    UNSAFE_PATH = "unsafe_path"
    IO_ERROR = "io_error"
    CONTRACT = "contract"
    INVARIANT = "invariant"


class WorkspaceReconcileStatus(StrEnum):
    """Whether disk discovery was complete enough to commit."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class WorkspaceDiscoverySkip:
    """One resource omitted during workspace disk discovery."""

    kind: WorkspaceDiscoverySkipKind
    path: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, WorkspaceDiscoverySkipKind):
            raise WorkspaceContractError(
                "WorkspaceDiscoverySkip.kind must be a WorkspaceDiscoverySkipKind"
            )
        if not self.path:
            raise WorkspaceContractError(
                "WorkspaceDiscoverySkip.path must be non-empty"
            )


@dataclass(frozen=True)
class WorkspaceReconcileResult:
    """Outcome of reconciling the workspace disk with its manifest."""

    manifest: WorkspaceManifest
    resources: tuple[WorkspaceResourceRecord, ...] = field(default_factory=tuple)
    skipped: tuple[WorkspaceDiscoverySkip, ...] = field(default_factory=tuple)
    limit_reached: bool = False
    status: WorkspaceReconcileStatus = WorkspaceReconcileStatus.COMPLETE
    changed: bool = False

    @property
    def complete(self) -> bool:
        return self.status is WorkspaceReconcileStatus.COMPLETE

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    def skip_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.skipped:
            key = item.kind.value
            counts[key] = counts.get(key, 0) + 1
        return counts


class WorkspaceReconciler:
    def __init__(
        self, *, settings: WorkspaceSettings, manifest_store: WorkspaceManifestStore
    ) -> None:
        self._settings = settings
        self._store = manifest_store
        self._classifier = WorkspaceResourceClassifier()

    def path_for(self, link: WorkspaceLink | str) -> Path:
        parsed = WorkspaceLink.parse(link) if isinstance(link, str) else link
        if not isinstance(parsed, WorkspaceLink):
            raise WorkspaceContractError("Workspace link is invalid")
        root = self._settings.root
        parts = parsed.path.parts
        if any(
            part in self._settings.ignore_dirs or part == ".tinysoul" for part in parts
        ):
            raise WorkspaceContractError("Workspace internal paths are not resources")
        if any(
            (root.joinpath(*parts[:index])).is_symlink()
            or (root.joinpath(*parts[:index])).is_junction()
            for index in range(1, len(parts) + 1)
        ):
            raise WorkspaceContractError(
                "Workspace links cannot traverse filesystem redirects"
            )
        try:
            resolved = resolve_under_root(root, parsed.relative_path)
        except FilesystemBoundaryError as exc:
            raise WorkspaceContractError(
                "Workspace link escapes its owner root"
            ) from exc
        if self.is_internal_path(resolved):
            raise WorkspaceContractError("Workspace internal paths are not resources")
        return resolved

    def is_internal_path(self, path: Path) -> bool:
        resolved = path.resolve()
        metadata = self._store.path.parent.resolve()
        trash = self._settings.trash_root.resolve()
        return (
            resolved == self._store.path.resolve()
            or resolved == trash
            or trash in resolved.parents
            or (
                metadata != self._settings.root.resolve()
                and (resolved == metadata or metadata in resolved.parents)
            )
        )

    def inspect_record(
        self, path: Path, previous: WorkspaceResourceRecord | None = None
    ) -> WorkspaceResourceRecord:
        try:
            relative = path.relative_to(self._settings.root.resolve()).as_posix()
            link = WorkspaceLink.from_relative_path(relative)
            resolved = self.path_for(link)
            stat = resolved.stat()
            if resolved.is_dir():
                kind, media_type, suffix, label = (
                    WorkspaceResourceKind.DIRECTORY,
                    "inode/directory",
                    "",
                    "Directory",
                )
            elif resolved.is_file():
                classification = self._classifier.classify(resolved)
                kind, media_type, suffix = (
                    classification.kind,
                    classification.media_type,
                    classification.suffix,
                )
                label = classification.summary_label
            else:
                raise WorkspaceContractError(
                    "Workspace resource must be a regular file or directory"
                )
        except FileNotFoundError as exc:
            raise WorkspaceContractError("Workspace resource does not exist") from exc
        except OSError as exc:
            raise WorkspaceIOError("Workspace resource cannot be inspected") from exc
        return WorkspaceResourceRecord(
            link=str(link),
            relative_path=relative,
            kind=kind,
            media_type=media_type,
            suffix=suffix,
            summary=f"{label}, {stat.st_size} bytes",
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            description=previous.description if previous else "",
            tags=previous.tags if previous else (),
        )

    def reconcile(self) -> WorkspaceReconcileResult:
        try:
            self._settings.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceIOError("Workspace root cannot be prepared") from exc
        current = self._store.load()
        root = self._settings.root.resolve()
        previous = {root / record.relative_path: record for record in current.resources}
        resources: list[WorkspaceResourceRecord] = []
        skipped: list[WorkspaceDiscoverySkip] = []
        limit_reached = False

        def walk_error(error: OSError) -> None:
            skipped.append(
                WorkspaceDiscoverySkip(WorkspaceDiscoverySkipKind.IO_ERROR, "directory")
            )

        for directory, names, filenames in os.walk(
            root, onerror=walk_error, followlinks=False
        ):
            parent = Path(directory)
            names[:] = sorted(
                name
                for name in names
                if name not in self._settings.ignore_dirs and name != ".tinysoul"
            )
            for name in (*names, *sorted(filenames)):
                path = parent / name
                if self.is_internal_path(path):
                    if name in names:
                        names.remove(name)
                    continue
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or path.is_junction():
                    if name in names:
                        names.remove(name)
                    skipped.append(
                        WorkspaceDiscoverySkip(
                            WorkspaceDiscoverySkipKind.UNSAFE_PATH, relative
                        )
                    )
                    continue
                if len(resources) >= self._settings.max_files:
                    limit_reached = True
                    break
                try:
                    resources.append(self.inspect_record(path, previous.get(path)))
                except WorkspaceContractError:
                    skipped.append(
                        WorkspaceDiscoverySkip(
                            WorkspaceDiscoverySkipKind.CONTRACT, relative
                        )
                    )
                except WorkspaceIOError:
                    skipped.append(
                        WorkspaceDiscoverySkip(
                            WorkspaceDiscoverySkipKind.IO_ERROR, relative
                        )
                    )
            if limit_reached:
                break
        ordered = tuple(sorted(resources, key=lambda record: record.link))
        # An incomplete scan cannot erase metadata for unvisited resources.
        complete = not limit_reached and not any(
            item.kind is not WorkspaceDiscoverySkipKind.UNSAFE_PATH for item in skipped
        )
        manifest = replace(current, resources=ordered) if complete else current
        changed = manifest != current
        if changed:
            self._store.save(manifest)
        return WorkspaceReconcileResult(
            manifest=manifest,
            resources=ordered,
            skipped=tuple(skipped),
            limit_reached=limit_reached,
            changed=changed,
            status=(
                WorkspaceReconcileStatus.COMPLETE
                if complete
                else WorkspaceReconcileStatus.INCOMPLETE
            ),
        )
