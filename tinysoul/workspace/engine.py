"""Workspace module assembly facade."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from threading import RLock

from tinysoul.infra.filesystem import (
    FilesystemBoundaryError,
    atomic_write_bytes,
    atomic_write_text,
    read_text_line_slice,
    read_text_prefix,
    resolve_under_root,
)

from .config import WorkspaceSettings
from .errors import (
    WorkspaceContractError,
    WorkspaceError,
    WorkspaceImageValidationError,
    WorkspaceIOError,
    WorkspaceReconciliationError,
)
from .links import WorkspaceLink
from .manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
)
from .reconcile import WorkspaceReconcileResult, WorkspaceReconciler
from .resources import WorkspaceResourceClassifier, image_data_matches


@dataclass(frozen=True)
class WorkspaceTextRead:
    """Bounded text read result for a workspace resource."""

    link: str
    text: str
    truncated: bool
    size: int
    digest: str


@dataclass(frozen=True)
class WorkspaceImageRead:
    """A complete image resource prepared for an LLM image part."""

    link: str
    data: bytes
    media_type: str
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
        classifier = WorkspaceResourceClassifier()
        self._reconciler = WorkspaceReconciler(
            settings=settings,
            manifest_store=manifest_store,
            classifier=classifier,
        )
        self._lock = RLock()

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
        with self._lock:
            return self._manifest_store.load()

    def snapshot(self) -> WorkspaceManifest:
        """Return the persisted state used for Context synchronization."""

        return self.load_manifest()

    def set_description(
        self,
        link: WorkspaceLink | str,
        description: str,
        *,
        expected_digest: str,
    ) -> WorkspaceResourceRecord:
        """Attach a bounded semantic description to the current resource digest."""

        with self._lock:
            return self._set_description(
                link,
                description,
                expected_digest=expected_digest,
            )

    def _set_description(
        self,
        link: WorkspaceLink | str,
        description: str,
        *,
        expected_digest: str,
    ) -> WorkspaceResourceRecord:

        if not isinstance(description, str) or not description.strip():
            raise WorkspaceContractError(
                "Workspace description must be a non-empty string"
            )
        normalized = description.strip()
        if len(normalized) > 2000:
            raise WorkspaceContractError(
                "Workspace description cannot exceed 2000 characters"
            )
        if not expected_digest:
            raise WorkspaceContractError(
                "Workspace description requires an expected digest"
            )
        reconciliation = self.reconcile()
        if not reconciliation.complete:
            raise WorkspaceReconciliationError(
                "Workspace description could not complete disk reconciliation"
            )
        parsed = WorkspaceLink.parse(link) if isinstance(link, str) else link
        link_value = str(parsed)
        records = list(reconciliation.manifest.resources)
        index = next(
            (index for index, record in enumerate(records) if record.link == link_value),
            None,
        )
        if index is None:
            raise WorkspaceContractError(
                f"Workspace resource does not exist: {link_value}"
            )
        current = records[index]
        if current.digest != expected_digest:
            raise WorkspaceContractError(
                f"Workspace resource digest mismatch: {link_value}"
            )
        observed = self._inspect_record(link_value)
        if observed.digest != expected_digest:
            raise WorkspaceContractError(
                f"Workspace resource changed while being described: {link_value}"
            )
        described = replace(
            observed,
            description=normalized,
            described_digest=observed.digest,
        )
        if described == current:
            return current
        records[index] = described
        manifest = WorkspaceManifest(
            revision=reconciliation.manifest.revision + 1,
            resources=tuple(records),
        )
        self._manifest_store.save(manifest)
        return described

    def inspect(self, link: WorkspaceLink | str) -> WorkspaceResourceRecord:
        """Inspect one disk resource without changing the manifest."""

        return self._inspect_record(link)

    def _inspect_record(self, link: WorkspaceLink | str) -> WorkspaceResourceRecord:
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
        record = self._inspect_record(link)
        if record.kind is not WorkspaceResourceKind.TEXT:
            raise WorkspaceContractError(
                f"Workspace resource is not directly readable text: {record.link}"
            )
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

    def read_image(
        self,
        link: WorkspaceLink | str,
        *,
        max_bytes: int | None = None,
    ) -> WorkspaceImageRead:
        limit = self._settings.max_image_bytes if max_bytes is None else max_bytes
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise WorkspaceContractError("Workspace image read limit must be positive")
        record = self._inspect_record(link)
        if record.kind is not WorkspaceResourceKind.IMAGE:
            raise WorkspaceContractError(
                f"Workspace resource is not a directly readable image: {record.link}"
            )
        if record.size > limit:
            raise WorkspaceContractError(
                f"Workspace image exceeds the read limit: {record.link}"
            )
        path = self.path_for(record.link)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to read workspace image: {exc}") from exc
        if len(data) > limit:
            raise WorkspaceContractError(
                f"Workspace image exceeds the read limit: {record.link}"
            )
        if not image_data_matches(record.media_type, data):
            raise WorkspaceImageValidationError(
                "Workspace image content does not match its media type: "
                f"{record.link}"
            )
        return WorkspaceImageRead(
            link=record.link,
            data=data,
            media_type=record.media_type,
            size=len(data),
            digest=sha256(data).hexdigest(),
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
        record = self._inspect_record(link)
        if record.kind is not WorkspaceResourceKind.TEXT:
            raise WorkspaceContractError(
                f"Workspace resource is not directly readable text: {record.link}"
            )
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
        with self._lock:
            return self._write_text(
                link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest,
            )

    def _write_text(
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
                current = self._inspect_record(str(parsed))
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
        existed = path.exists()
        previous = self._read_rollback_bytes(path) if existed else None
        try:
            atomic_write_text(path, text)
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to write workspace resource: {exc}") from exc
        return self._reconcile_mutation(
            path,
            link=str(parsed),
            previous=previous,
        )

    def patch_text(
        self,
        link: WorkspaceLink | str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str = "",
    ) -> WorkspaceResourceRecord:
        with self._lock:
            return self._patch_text(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )

    def _patch_text(
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
        record = self._inspect_record(link)
        path = self.path_for(record.link)
        self._check_mutable_path(path, link=record.link)
        if expected_digest and record.digest != expected_digest:
            raise WorkspaceContractError(
                f"Workspace resource digest mismatch: {record.link}"
            )
        previous = self._read_rollback_bytes(path)
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
        return self._reconcile_mutation(
            path,
            link=record.link,
            previous=previous,
        )

    def delete_resource(self, link: WorkspaceLink | str) -> WorkspaceResourceRecord:
        with self._lock:
            return self._delete_resource(link)

    def _delete_resource(
        self,
        link: WorkspaceLink | str,
    ) -> WorkspaceResourceRecord:
        record = self._inspect_record(link)
        path = self.path_for(record.link)
        self._check_mutable_path(path, link=record.link)
        previous = self._read_rollback_bytes(path)
        try:
            path.unlink()
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to delete workspace resource: {exc}") from exc
        try:
            reconciliation = self.reconcile()
            if not reconciliation.complete:
                raise WorkspaceReconciliationError(
                    "Workspace delete could not complete disk reconciliation"
                )
        except WorkspaceError as exc:
            self._rollback_mutation(path, previous=previous, cause=exc)
            raise
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

    def reconcile(self) -> WorkspaceReconcileResult:
        with self._lock:
            return self._reconciler.reconcile()

    def _record_for(self, path: Path) -> WorkspaceResourceRecord | None:
        return self._reconciler.inspect_record(path)

    def _is_internal_path(self, path: Path) -> bool:
        return self._reconciler.is_internal_path(path)

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

    def _reconcile_mutation(
        self,
        path: Path,
        *,
        link: str,
        previous: bytes | None,
    ) -> WorkspaceResourceRecord:
        try:
            record = self._inspect_record(link)
            reconciliation = self.reconcile()
            if not reconciliation.complete:
                raise WorkspaceReconciliationError(
                    "Workspace mutation could not complete disk reconciliation"
                )
            return record
        except WorkspaceError as exc:
            self._rollback_mutation(path, previous=previous, cause=exc)
            raise

    @staticmethod
    def _read_rollback_bytes(path: Path) -> bytes:
        try:
            return path.read_bytes()
        except OSError as exc:
            raise WorkspaceIOError(
                f"Failed to stage workspace rollback data: {exc}"
            ) from exc

    @staticmethod
    def _rollback_mutation(
        path: Path,
        *,
        previous: bytes | None,
        cause: WorkspaceError,
    ) -> None:
        try:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, previous)
        except OSError as rollback_error:
            raise WorkspaceIOError(
                "Workspace reconciliation failed and file rollback also failed: "
                f"{rollback_error}"
            ) from cause


class WorkspaceEngineBuilder:
    """Build a WorkspaceEngine from parsed settings."""

    def __init__(self, settings: WorkspaceSettings) -> None:
        self._settings = settings

    def build(self) -> WorkspaceEngine:
        if self._settings.root.exists() and not self._settings.root.is_dir():
            raise WorkspaceIOError("Workspace root must be a directory")
        engine = WorkspaceEngine(
            settings=self._settings,
            manifest_store=WorkspaceManifestStore(self._settings.manifest_path),
        )
        engine.load_manifest()
        return engine


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
