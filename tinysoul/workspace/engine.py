"""Workspace module assembly facade."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import os

from tinysoul.context.working import WorkspaceResource
from tinysoul.infra.filesystem import (
    FilesystemBoundaryError,
    atomic_write_text,
    file_digest,
    read_text_line_slice,
    read_text_prefix,
    resolve_under_root,
)

from .config import WorkspaceSettings
from .errors import WorkspaceContractError, WorkspaceInvariantError, WorkspaceIOError
from .links import WorkspaceLink
from .manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
)


class WorkspaceScanSkipKind(StrEnum):
    """Stable workspace scan skip reasons."""

    INTERNAL = "internal"
    UNSAFE_PATH = "unsafe_path"
    IO_ERROR = "io_error"
    CONTRACT = "contract"
    INVARIANT = "invariant"


@dataclass(frozen=True)
class WorkspaceScanSkip:
    """One resource skipped during workspace scanning."""

    kind: WorkspaceScanSkipKind
    path: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, WorkspaceScanSkipKind):
            raise WorkspaceContractError(
                "WorkspaceScanSkip.kind must be a WorkspaceScanSkipKind"
            )
        if not self.path:
            raise WorkspaceContractError("WorkspaceScanSkip.path must be non-empty")


@dataclass(frozen=True)
class WorkspaceScanResult:
    """Result of a workspace scan."""

    manifest: WorkspaceManifest
    resources: tuple[WorkspaceResourceRecord, ...] = field(default_factory=tuple)
    skipped: tuple[WorkspaceScanSkip, ...] = field(default_factory=tuple)
    limit_reached: bool = False

    def to_working_resources(self) -> tuple[WorkspaceResource, ...]:
        return tuple(
            WorkspaceResource(link=resource.link, summary=resource.summary)
            for resource in self.resources
        )

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
class WorkspaceTextRead:
    """Bounded text read result for a workspace resource."""

    link: str
    text: str
    truncated: bool
    size: int
    digest: str


@dataclass(frozen=True)
class WorkspaceTextSlice:
    """A bounded text slice for temporary workspace prompt input."""

    link: str
    range_label: str
    text: str
    truncated: bool
    size: int
    digest: str

    def __post_init__(self) -> None:
        if not self.link:
            raise WorkspaceContractError("WorkspaceTextSlice.link must be non-empty")
        if not self.range_label:
            raise WorkspaceContractError(
                "WorkspaceTextSlice.range_label must be non-empty"
            )
        if self.size < 0:
            raise WorkspaceContractError("WorkspaceTextSlice.size must be non-negative")


@dataclass(frozen=True)
class WorkspacePromptInput:
    """Workspace text slices for a temporary task prompt."""

    slices: tuple[WorkspaceTextSlice, ...]

    def __post_init__(self) -> None:
        if not self.slices:
            raise WorkspaceContractError(
                "WorkspacePromptInput requires at least one text slice"
            )

    @property
    def truncated(self) -> bool:
        return any(text_slice.truncated for text_slice in self.slices)

    def render(self) -> str:
        return "\n\n".join(
            _render_prompt_slice(text_slice) for text_slice in self.slices
        )


@dataclass(frozen=True)
class _WorkspaceScanBuild:
    resources: tuple[WorkspaceResourceRecord, ...]
    skipped: tuple[WorkspaceScanSkip, ...]
    limit_reached: bool


@dataclass(frozen=True)
class _WorkspaceRecordBuild:
    record: WorkspaceResourceRecord | None = None
    skip_kind: WorkspaceScanSkipKind | None = None


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

    def describe(self, link: WorkspaceLink | str) -> WorkspaceResourceRecord:
        path = self.path_for(link)
        if self._is_internal_path(path):
            raise WorkspaceContractError(f"Workspace resource is internal: {link}")
        if not path.exists():
            raise WorkspaceContractError(f"Workspace resource does not exist: {link}")
        if not path.is_file():
            raise WorkspaceContractError(f"Workspace resource is not a file: {link}")
        record = self._record_for(path)
        if record is None:
            raise WorkspaceContractError(f"Workspace resource cannot be described: {link}")
        self._upsert_manifest_record(record)
        return record

    def read_text(
        self,
        link: WorkspaceLink | str,
        *,
        max_chars: int | None = None,
    ) -> WorkspaceTextRead:
        limit = self._settings.max_read_chars if max_chars is None else max_chars
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise WorkspaceContractError("Workspace read limit must be positive")
        record = self.describe(link)
        path = self.path_for(record.link)
        try:
            read = read_text_prefix(path, max_chars=limit)
        except UnicodeDecodeError as exc:
            raise WorkspaceContractError(
                f"Workspace resource is not readable as UTF-8 text: {record.link}"
            ) from exc
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to read workspace resource: {exc}") from exc
        return WorkspaceTextRead(
            link=record.link,
            text=read.text,
            truncated=read.truncated,
            size=record.size,
            digest=record.digest,
        )

    def read_text_slice(
        self,
        link: WorkspaceLink | str,
        *,
        start_line: int = 1,
        max_lines: int | None = None,
        max_chars: int | None = None,
    ) -> WorkspaceTextSlice:
        limit = self._settings.max_read_chars if max_chars is None else max_chars
        if (
            isinstance(start_line, bool)
            or not isinstance(start_line, int)
            or start_line <= 0
        ):
            raise WorkspaceContractError("Workspace read start_line must be positive")
        if max_lines is not None and (
            isinstance(max_lines, bool)
            or not isinstance(max_lines, int)
            or max_lines <= 0
        ):
            raise WorkspaceContractError("Workspace read max_lines must be positive")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise WorkspaceContractError("Workspace read limit must be positive")
        record = self.describe(link)
        path = self.path_for(record.link)
        try:
            read = read_text_line_slice(
                path,
                start_line=start_line,
                max_lines=max_lines,
                max_chars=limit,
            )
        except UnicodeDecodeError as exc:
            raise WorkspaceContractError(
                f"Workspace resource is not readable as UTF-8 text: {record.link}"
            ) from exc
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to read workspace resource: {exc}") from exc
        if read.end_line >= read.start_line:
            range_label = f"lines:{read.start_line}-{read.end_line}"
        else:
            range_label = f"lines:{start_line}-empty"
        return WorkspaceTextSlice(
            link=record.link,
            range_label=range_label,
            text=read.text,
            truncated=read.truncated,
            size=record.size,
            digest=record.digest,
        )

    def write_target_exists(self, link: WorkspaceLink | str) -> bool:
        parsed = WorkspaceLink.parse(link) if isinstance(link, str) else link
        path = self.path_for(parsed)
        self._check_mutable_path(path, link=str(parsed))
        if path.exists() and not path.is_file():
            raise WorkspaceContractError(f"Workspace resource is not a file: {parsed}")
        parent = path.parent
        if parent.exists() and not parent.is_dir():
            raise WorkspaceContractError(
                f"Workspace resource parent is not a directory: {parsed}"
            )
        return path.exists()

    def write_text(
        self,
        link: WorkspaceLink | str,
        text: str,
        *,
        overwrite: bool = False,
        expected_digest: str = "",
    ) -> WorkspaceResourceRecord:
        if not isinstance(text, str):
            raise WorkspaceContractError("Workspace write text must be a string")
        if not isinstance(overwrite, bool):
            raise WorkspaceContractError("Workspace write overwrite must be a boolean")
        if not isinstance(expected_digest, str):
            raise WorkspaceContractError(
                "Workspace write expected_digest must be a string"
            )
        parsed = WorkspaceLink.parse(link) if isinstance(link, str) else link
        path = self.path_for(parsed)
        self._check_mutable_path(path, link=str(parsed))
        if path.exists():
            if not path.is_file():
                raise WorkspaceContractError(
                    f"Workspace resource is not a file: {parsed}"
                )
            if not overwrite:
                raise WorkspaceContractError(
                    f"Workspace resource already exists: {parsed}"
                )
            if expected_digest:
                current = self.describe(str(parsed))
                if current.digest != expected_digest:
                    raise WorkspaceContractError(
                        f"Workspace resource digest mismatch: {parsed}"
                    )
        elif expected_digest:
            raise WorkspaceContractError(
                f"Workspace resource does not exist for digest check: {parsed}"
            )
        parent = path.parent
        if parent.exists() and not parent.is_dir():
            raise WorkspaceContractError(
                f"Workspace resource parent is not a directory: {parsed}"
            )
        try:
            atomic_write_text(path, text)
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to write workspace resource: {exc}") from exc
        return self.describe(str(parsed))

    def patch_text(
        self,
        link: WorkspaceLink | str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str = "",
    ) -> WorkspaceResourceRecord:
        if not isinstance(old_text, str) or not old_text:
            raise WorkspaceContractError(
                "Workspace patch old_text must be a non-empty string"
            )
        if not isinstance(new_text, str):
            raise WorkspaceContractError("Workspace patch new_text must be a string")
        if not isinstance(expected_digest, str):
            raise WorkspaceContractError(
                "Workspace patch expected_digest must be a string"
            )
        record = self.describe(link)
        path = self.path_for(record.link)
        self._check_mutable_path(path, link=record.link)
        if expected_digest and record.digest != expected_digest:
            raise WorkspaceContractError(
                f"Workspace resource digest mismatch: {record.link}"
            )
        try:
            current = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceContractError(
                f"Workspace resource is not readable as UTF-8 text: {record.link}"
            ) from exc
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to read workspace resource: {exc}") from exc
        matches = current.count(old_text)
        if matches == 0:
            raise WorkspaceContractError(
                f"Workspace patch old_text was not found: {record.link}"
            )
        if matches > 1:
            raise WorkspaceContractError(
                f"Workspace patch old_text is not unique: {record.link}"
            )
        try:
            atomic_write_text(path, current.replace(old_text, new_text, 1))
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to write workspace resource: {exc}") from exc
        return self.describe(record.link)

    def delete_resource(self, link: WorkspaceLink | str) -> WorkspaceResourceRecord:
        record = self.describe(link)
        path = self.path_for(record.link)
        self._check_mutable_path(path, link=record.link)
        try:
            path.unlink()
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to delete workspace resource: {exc}") from exc
        self._remove_manifest_record(record.link)
        return record

    def prepare_task_input(
        self,
        links: Sequence[WorkspaceLink | str],
        *,
        max_chars_per_resource: int | None = None,
    ) -> WorkspacePromptInput:
        if not links:
            raise WorkspaceContractError(
                "Workspace task input requires at least one resource link"
            )
        if max_chars_per_resource is not None and (
            isinstance(max_chars_per_resource, bool)
            or not isinstance(max_chars_per_resource, int)
            or max_chars_per_resource <= 0
        ):
            raise WorkspaceContractError(
                "Workspace task input read limit must be positive"
            )
        limit = (
            self._settings.max_read_chars
            if max_chars_per_resource is None
            else max_chars_per_resource
        )
        slices = tuple(
            _slice_from_read(
                self.read_text(link, max_chars=limit),
                range_label=f"prefix:{limit}",
            )
            for link in links
        )
        return WorkspacePromptInput(slices=slices)

    def scan(self) -> WorkspaceScanResult:
        self._settings.root.mkdir(parents=True, exist_ok=True)
        scan = self._scan_resources()
        manifest = WorkspaceManifest(resources=scan.resources)
        self._manifest_store.save(manifest)
        return WorkspaceScanResult(
            manifest=manifest,
            resources=scan.resources,
            skipped=scan.skipped,
            limit_reached=scan.limit_reached,
        )

    def _scan_resources(self) -> _WorkspaceScanBuild:
        root = self._settings.root
        ignored = set(self._settings.ignore_dirs)
        resources: list[WorkspaceResourceRecord] = []
        skipped: list[WorkspaceScanSkip] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name for name in sorted(dirnames) if name not in ignored and not name.startswith(".")
            ]
            for filename in sorted(filenames):
                if len(resources) >= self._settings.max_files:
                    return _WorkspaceScanBuild(
                        resources=tuple(resources),
                        skipped=tuple(skipped),
                        limit_reached=True,
                    )
                path = Path(dirpath) / filename
                if self._is_internal_path(path):
                    skipped.append(
                        WorkspaceScanSkip(
                            kind=WorkspaceScanSkipKind.INTERNAL,
                            path=self._scan_path_label(path),
                        )
                    )
                    continue
                build = self._record_for_scan(path)
                if build.record is not None:
                    resources.append(build.record)
                elif build.skip_kind is not None:
                    skipped.append(
                        WorkspaceScanSkip(
                            kind=build.skip_kind,
                            path=self._scan_path_label(path),
                        )
                    )
        return _WorkspaceScanBuild(
            resources=tuple(resources),
            skipped=tuple(skipped),
            limit_reached=False,
        )

    def _record_for(self, path: Path) -> WorkspaceResourceRecord | None:
        return self._record_for_scan(path).record

    def _record_for_scan(self, path: Path) -> _WorkspaceRecordBuild:
        try:
            relative = path.relative_to(self._settings.root).as_posix()
            link = WorkspaceLink.from_relative_path(relative)
            resolved = resolve_under_root(self._settings.root, link.relative_path)
            stat = resolved.stat()
        except FilesystemBoundaryError:
            return _WorkspaceRecordBuild(skip_kind=WorkspaceScanSkipKind.UNSAFE_PATH)
        except ValueError:
            return _WorkspaceRecordBuild(skip_kind=WorkspaceScanSkipKind.UNSAFE_PATH)
        except OSError:
            return _WorkspaceRecordBuild(skip_kind=WorkspaceScanSkipKind.IO_ERROR)
        except WorkspaceContractError:
            return _WorkspaceRecordBuild(skip_kind=WorkspaceScanSkipKind.CONTRACT)
        except WorkspaceInvariantError:
            return _WorkspaceRecordBuild(skip_kind=WorkspaceScanSkipKind.INVARIANT)
        digest = ""
        try:
            digest = file_digest(resolved, limit_bytes=1024 * 1024)
        except OSError:
            digest = ""
        suffix = path.suffix or "file"
        summary = f"{suffix} file, {stat.st_size} bytes"
        record = WorkspaceResourceRecord(
            link=str(link),
            relative_path=relative,
            kind=WorkspaceResourceKind.FILE,
            summary=summary,
            size=stat.st_size,
            mtime=stat.st_mtime,
            digest=digest,
        )
        return _WorkspaceRecordBuild(record=record)

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

    def _scan_path_label(self, path: Path) -> str:
        try:
            return path.relative_to(self._settings.root).as_posix()
        except ValueError:
            return path.name

    def _check_mutable_path(self, path: Path, *, link: str) -> None:
        if self._is_internal_path(path):
            raise WorkspaceContractError(f"Workspace resource is internal: {link}")
        if self._has_ignored_parent(path):
            raise WorkspaceContractError(f"Workspace resource is ignored: {link}")

    def _has_ignored_parent(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self._settings.root.resolve())
        except ValueError:
            return False
        ignored = set(self._settings.ignore_dirs)
        return any(part in ignored or part.startswith(".") for part in relative.parts[:-1])

    def _upsert_manifest_record(self, record: WorkspaceResourceRecord) -> None:
        manifest = self.load_manifest()
        records: list[WorkspaceResourceRecord] = []
        replaced = False
        for item in manifest.resources:
            if item.link == record.link:
                records.append(record)
                replaced = True
                continue
            records.append(item)
        if not replaced:
            records.append(record)
        self._manifest_store.save(WorkspaceManifest(resources=tuple(records)))

    def _remove_manifest_record(self, link: str) -> None:
        manifest = self.load_manifest()
        records = tuple(item for item in manifest.resources if item.link != link)
        self._manifest_store.save(WorkspaceManifest(resources=records))


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


def _slice_from_read(read: WorkspaceTextRead, *, range_label: str) -> WorkspaceTextSlice:
    return WorkspaceTextSlice(
        link=read.link,
        range_label=range_label,
        text=read.text,
        truncated=read.truncated,
        size=read.size,
        digest=read.digest,
    )


def _render_prompt_slice(text_slice: WorkspaceTextSlice) -> str:
    truncated = "true" if text_slice.truncated else "false"
    lines = [
        f"## {text_slice.link}",
        f"range: {text_slice.range_label}",
        f"size: {text_slice.size} bytes",
        f"digest: {text_slice.digest}",
        f"truncated: {truncated}",
        "",
        text_slice.text,
    ]
    return "\n".join(lines)
