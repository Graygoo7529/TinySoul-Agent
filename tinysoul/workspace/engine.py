"""Workspace module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os

from tinysoul.context.working import WorkspaceResource
from tinysoul.infra.filesystem import FilesystemBoundaryError, file_digest, resolve_under_root

from .config import WorkspaceSettings
from .errors import WorkspaceContractError, WorkspaceInvariantError, WorkspaceIOError
from .links import WorkspaceLink
from .manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
)


@dataclass(frozen=True)
class WorkspaceScanResult:
    """Result of a workspace scan."""

    manifest: WorkspaceManifest
    resources: tuple[WorkspaceResourceRecord, ...] = field(default_factory=tuple)

    def to_working_resources(self) -> tuple[WorkspaceResource, ...]:
        return tuple(
            WorkspaceResource(link=resource.link, summary=resource.summary)
            for resource in self.resources
        )


class WorkspaceEngine:
    """Workspace resource management entry point."""

    def __init__(
        self,
        *,
        settings: WorkspaceSettings,
        manifest_store: WorkspaceManifestStore,
    ) -> None:
        self._settings = settings
        self._manifest_store = manifest_store

    @property
    def root(self) -> Path:
        return self._settings.root

    @property
    def settings(self) -> WorkspaceSettings:
        return self._settings

    def parse_link(self, value: str) -> WorkspaceLink:
        return WorkspaceLink.parse(value)

    def path_for(self, link: WorkspaceLink | str) -> Path:
        parsed = WorkspaceLink.parse(link) if isinstance(link, str) else link
        try:
            return resolve_under_root(self._settings.root, parsed.relative_path)
        except FilesystemBoundaryError as exc:
            raise WorkspaceContractError(str(exc)) from exc

    def load_manifest(self) -> WorkspaceManifest:
        return self._manifest_store.load()

    def scan(self) -> WorkspaceScanResult:
        self._settings.root.mkdir(parents=True, exist_ok=True)
        resources = self._scan_resources()
        manifest = WorkspaceManifest(resources=resources)
        self._manifest_store.save(manifest)
        return WorkspaceScanResult(manifest=manifest, resources=resources)

    def _scan_resources(self) -> tuple[WorkspaceResourceRecord, ...]:
        root = self._settings.root
        ignored = set(self._settings.ignore_dirs)
        resources: list[WorkspaceResourceRecord] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name for name in sorted(dirnames) if name not in ignored and not name.startswith(".")
            ]
            for filename in sorted(filenames):
                if len(resources) >= self._settings.max_files:
                    return tuple(resources)
                path = Path(dirpath) / filename
                if self._is_internal_path(path):
                    continue
                record = self._record_for(path)
                if record is not None:
                    resources.append(record)
        return tuple(resources)

    def _record_for(self, path: Path) -> WorkspaceResourceRecord | None:
        try:
            relative = path.relative_to(self._settings.root).as_posix()
            link = WorkspaceLink.from_relative_path(relative)
            resolved = resolve_under_root(self._settings.root, link.relative_path)
            stat = resolved.stat()
        except (
            FilesystemBoundaryError,
            OSError,
            ValueError,
            WorkspaceContractError,
            WorkspaceInvariantError,
        ):
            return None
        digest = ""
        try:
            digest = file_digest(resolved, limit_bytes=1024 * 1024)
        except OSError:
            digest = ""
        suffix = path.suffix or "file"
        summary = f"{suffix} file, {stat.st_size} bytes"
        return WorkspaceResourceRecord(
            link=str(link),
            relative_path=relative,
            kind=WorkspaceResourceKind.FILE,
            summary=summary,
            size=stat.st_size,
            mtime=stat.st_mtime,
            digest=digest,
        )

    def _is_internal_path(self, path: Path) -> bool:
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


class WorkspaceEngineBuilder:
    """Build a WorkspaceEngine from parsed settings."""

    def __init__(self, settings: WorkspaceSettings) -> None:
        self._settings = settings

    def build(self) -> WorkspaceEngine:
        if self._settings.root.exists() and not self._settings.root.is_dir():
            raise WorkspaceIOError("Workspace root must be a directory")
        return WorkspaceEngine(
            settings=self._settings,
            manifest_store=WorkspaceManifestStore(self._settings.manifest_path),
        )
