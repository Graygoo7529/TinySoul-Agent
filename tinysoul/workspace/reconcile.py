"""Workspace disk discovery and manifest reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from stat import S_ISREG
import os

from tinysoul.infra.filesystem import (
    FilesystemBoundaryError,
    file_digest,
    resolve_under_root,
)

from .config import WorkspaceSettings
from .errors import (
    WorkspaceContractError,
    WorkspaceIOError,
    WorkspaceInvariantError,
)
from .links import WorkspaceLink
from .manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
    WorkspaceResourceRecord,
)
from .resources import WorkspaceResourceClassifier


class WorkspaceDiscoverySkipKind(StrEnum):
    """Stable reasons why disk discovery omitted a resource."""

    INTERNAL = "internal"
    UNSAFE_PATH = "unsafe_path"
    IO_ERROR = "io_error"
    CONTRACT = "contract"
    INVARIANT = "invariant"
    CONCURRENT_CHANGE = "concurrent_change"


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


@dataclass(frozen=True)
class _WorkspaceDiscovery:
    resources: tuple[WorkspaceResourceRecord, ...]
    skipped: tuple[WorkspaceDiscoverySkip, ...]
    limit_reached: bool


@dataclass(frozen=True)
class _WorkspaceRecordBuild:
    record: WorkspaceResourceRecord | None = None
    skip_kind: WorkspaceDiscoverySkipKind | None = None


class WorkspaceReconciler:
    """Discover disk resources and atomically commit a complete manifest."""

    def __init__(
        self,
        *,
        settings: WorkspaceSettings,
        manifest_store: WorkspaceManifestStore,
        classifier: WorkspaceResourceClassifier,
    ) -> None:
        self._settings = settings
        self._manifest_store = manifest_store
        self._classifier = classifier

    def reconcile(self) -> WorkspaceReconcileResult:
        try:
            self._settings.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to prepare workspace root: {exc}") from exc
        current = self._manifest_store.load()
        discovery = self._discover(
            {record.link: record for record in current.resources}
        )
        if self._incomplete(discovery):
            return self._incomplete_result(current, discovery)

        resources = tuple(sorted(discovery.resources, key=lambda item: item.link))
        changed = resources != current.resources
        if changed:
            unstable = self._unstable_resources(resources)
            if unstable:
                skipped = (*discovery.skipped, *unstable)
                return WorkspaceReconcileResult(
                    manifest=current,
                    resources=resources,
                    skipped=skipped,
                    status=WorkspaceReconcileStatus.INCOMPLETE,
                )
        manifest = WorkspaceManifest(
            revision=current.revision + 1 if changed else current.revision,
            resources=resources,
        )
        if changed:
            self._manifest_store.save(manifest)
        return WorkspaceReconcileResult(
            manifest=manifest,
            resources=resources,
            skipped=discovery.skipped,
            status=WorkspaceReconcileStatus.COMPLETE,
            changed=changed,
        )

    def inspect_record(self, path: Path) -> WorkspaceResourceRecord | None:
        """Build one current record without mutating the manifest."""

        return self._record_for(path, previous=None).record

    def is_internal_path(self, path: Path) -> bool:
        path_resolved = path.resolve()
        manifest_path = self._manifest_store.path.resolve()
        if path_resolved == manifest_path:
            return True
        manifest_parent = manifest_path.parent
        if manifest_parent == self._settings.root.resolve():
            return False
        try:
            path_resolved.relative_to(manifest_parent)
        except ValueError:
            return False
        return True

    def _discover(
        self,
        current_records: dict[str, WorkspaceResourceRecord],
    ) -> _WorkspaceDiscovery:
        root = self._settings.root
        ignored = set(self._settings.ignore_dirs)
        resources: list[WorkspaceResourceRecord] = []
        skipped: list[WorkspaceDiscoverySkip] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name
                for name in sorted(dirnames)
                if name not in ignored and not name.startswith(".")
            ]
            for filename in sorted(filenames):
                if len(resources) >= self._settings.max_files:
                    return _WorkspaceDiscovery(
                        resources=tuple(resources),
                        skipped=tuple(skipped),
                        limit_reached=True,
                    )
                path = Path(dirpath) / filename
                if self.is_internal_path(path):
                    skipped.append(
                        WorkspaceDiscoverySkip(
                            kind=WorkspaceDiscoverySkipKind.INTERNAL,
                            path=self._path_label(path),
                        )
                    )
                    continue
                try:
                    relative = path.relative_to(root).as_posix()
                    previous = current_records.get(
                        str(WorkspaceLink.from_relative_path(relative))
                    )
                except (ValueError, WorkspaceContractError):
                    skipped.append(
                        WorkspaceDiscoverySkip(
                            kind=WorkspaceDiscoverySkipKind.UNSAFE_PATH,
                            path=self._path_label(path),
                        )
                    )
                    continue
                build = self._record_for(path, previous=previous)
                if build.record is not None:
                    resources.append(build.record)
                elif build.skip_kind is not None:
                    skipped.append(
                        WorkspaceDiscoverySkip(
                            kind=build.skip_kind,
                            path=self._path_label(path),
                        )
                    )
        return _WorkspaceDiscovery(
            resources=tuple(resources),
            skipped=tuple(skipped),
            limit_reached=False,
        )

    def _record_for(
        self,
        path: Path,
        *,
        previous: WorkspaceResourceRecord | None,
    ) -> _WorkspaceRecordBuild:
        try:
            relative = path.relative_to(self._settings.root).as_posix()
            link = WorkspaceLink.from_relative_path(relative)
            resolved = resolve_under_root(self._settings.root, link.relative_path)
            stat = resolved.stat()
        except (FilesystemBoundaryError, ValueError):
            return _WorkspaceRecordBuild(
                skip_kind=WorkspaceDiscoverySkipKind.UNSAFE_PATH
            )
        except OSError:
            return _WorkspaceRecordBuild(skip_kind=WorkspaceDiscoverySkipKind.IO_ERROR)
        except WorkspaceContractError:
            return _WorkspaceRecordBuild(skip_kind=WorkspaceDiscoverySkipKind.CONTRACT)
        except WorkspaceInvariantError:
            return _WorkspaceRecordBuild(skip_kind=WorkspaceDiscoverySkipKind.INVARIANT)

        classification = self._classifier.classify(path)
        if (
            previous is not None
            and previous.size == stat.st_size
            and previous.mtime_ns == stat.st_mtime_ns
        ):
            digest = previous.digest
        else:
            try:
                digest = file_digest(resolved)
            except OSError:
                return _WorkspaceRecordBuild(
                    skip_kind=WorkspaceDiscoverySkipKind.IO_ERROR
                )
        description = ""
        described_digest = ""
        if previous is not None and previous.described_digest == digest:
            description = previous.description
            described_digest = previous.described_digest
        return _WorkspaceRecordBuild(
            record=WorkspaceResourceRecord(
                link=str(link),
                relative_path=relative,
                kind=classification.kind,
                media_type=classification.media_type,
                suffix=classification.suffix,
                summary=f"{classification.summary_label}, {stat.st_size} bytes",
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                digest=digest,
                description=description,
                described_digest=described_digest,
            )
        )

    def _unstable_resources(
        self,
        resources: tuple[WorkspaceResourceRecord, ...],
    ) -> tuple[WorkspaceDiscoverySkip, ...]:
        unstable: list[WorkspaceDiscoverySkip] = []
        for record in resources:
            path = self._settings.root / Path(record.relative_path)
            try:
                stat = path.stat()
            except OSError:
                stat = None
            if (
                stat is None
                or not S_ISREG(stat.st_mode)
                or stat.st_size != record.size
                or stat.st_mtime_ns != record.mtime_ns
            ):
                unstable.append(
                    WorkspaceDiscoverySkip(
                        kind=WorkspaceDiscoverySkipKind.CONCURRENT_CHANGE,
                        path=record.relative_path,
                    )
                )
        return tuple(unstable)

    @staticmethod
    def _incomplete(discovery: _WorkspaceDiscovery) -> bool:
        return discovery.limit_reached or any(
            item.kind is not WorkspaceDiscoverySkipKind.INTERNAL
            for item in discovery.skipped
        )

    @staticmethod
    def _incomplete_result(
        current: WorkspaceManifest,
        discovery: _WorkspaceDiscovery,
    ) -> WorkspaceReconcileResult:
        return WorkspaceReconcileResult(
            manifest=current,
            resources=discovery.resources,
            skipped=discovery.skipped,
            limit_reached=discovery.limit_reached,
            status=WorkspaceReconcileStatus.INCOMPLETE,
        )

    def _path_label(self, path: Path) -> str:
        try:
            return path.relative_to(self._settings.root).as_posix()
        except ValueError:
            return path.name
