"""Workspace module assembly facade."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from threading import RLock
import os

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
    WorkspaceInvariantError,
    WorkspaceIOError,
    WorkspaceReconciliationError,
    WorkspaceTrashRestoreRequired,
)
from tinysoul.loop.day import BusinessDay
from .links import WorkspaceLink
from .manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
    WorkspaceRetention,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
)
from .reconcile import WorkspaceReconcileResult, WorkspaceReconciler
from .resources import WorkspaceResourceClassifier, image_data_matches
from .search import (
    WorkspaceSearchScope,
    WorkspaceSearchScopeKind,
    WorkspaceTextSearchResult,
    WorkspaceTextSearchService,
)
from .text import WorkspaceTextRangeRead, read_text_range as read_text_file_range
from .trash import WorkspaceTrashItem, WorkspaceTrashStore


_AUTO_RESTORE_TRASH_REASONS = frozenset(
    {"context_pressure", "trash_restore_context_rejected"}
)


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
class WorkspaceDocumentRead:
    """A complete bounded document resource for local conversion."""

    link: str
    data: bytes
    media_type: str
    suffix: str
    size: int
    digest: str
    retention: WorkspaceRetention
    owner_turn_id: str


@dataclass(frozen=True)
class WorkspaceBundleWrite:
    """One resource write in an atomic Workspace bundle mutation."""

    link: str
    data: bytes
    overwrite: bool = False
    expected_digest: str = ""
    retention: WorkspaceRetention | None = None
    owner_turn_id: str = ""

    def __post_init__(self) -> None:
        WorkspaceLink.parse(self.link)
        if not isinstance(self.data, bytes):
            raise WorkspaceContractError("Workspace bundle data must be bytes")
        if not isinstance(self.overwrite, bool):
            raise WorkspaceContractError("Workspace bundle overwrite must be boolean")
        if not isinstance(self.expected_digest, str):
            raise WorkspaceContractError(
                "Workspace bundle expected digest must be a string"
            )
        if self.retention is not None and not isinstance(
            self.retention, WorkspaceRetention
        ):
            raise WorkspaceContractError(
                "Workspace bundle retention must be a WorkspaceRetention or None"
            )
        if not isinstance(self.owner_turn_id, str):
            raise WorkspaceContractError(
                "Workspace bundle owner turn id must be a string"
            )


@dataclass(frozen=True)
class WorkspaceBundleResult:
    """Committed records and manifest for one Workspace bundle mutation."""

    manifest: WorkspaceManifest
    records: tuple[WorkspaceResourceRecord, ...]


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
class WorkspaceTextRangeResult:
    """A digest-bound bounded page from an explicit Workspace line range."""

    link: str
    digest: str
    size: int
    start_line: int
    end_line: int
    max_chars: int
    page: WorkspaceTextRangeRead


@dataclass(frozen=True)
class WorkspaceAnalysisReference:
    """One complete text reference for a Workspace analysis task."""

    source_id: str
    link: str
    text: str
    digest: str
    size: int
    end_line: int


@dataclass(frozen=True)
class WorkspaceAnalysisInput:
    """A complete bounded reference bundle for one analysis task."""

    references: tuple[WorkspaceAnalysisReference, ...]
    total_chars: int


class WorkspaceAnalysisBudgetReason(StrEnum):
    REFERENCE_COUNT = "reference_count_exceeded"
    REFERENCE_CHARS = "reference_chars_exceeded"
    SOURCE_CHARS = "source_chars_exceeded"


@dataclass(frozen=True)
class WorkspaceAnalysisBudgetFailure:
    reason: WorkspaceAnalysisBudgetReason
    limit: int
    observed: int
    offending_link: str = ""
    inspected: tuple[WorkspaceResourceRecord, ...] = ()


@dataclass(frozen=True)
class WorkspaceAnalysisPreparation:
    input: WorkspaceAnalysisInput | None = None
    failure: WorkspaceAnalysisBudgetFailure | None = None

    def __post_init__(self) -> None:
        if (self.input is None) == (self.failure is None):
            raise WorkspaceContractError(
                "Workspace analysis preparation requires exactly one outcome"
            )


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
        trash_store: WorkspaceTrashStore | None = None,
    ) -> None:
        self._settings = settings
        self._manifest_store = manifest_store
        self._trash_store = trash_store or WorkspaceTrashStore(settings.trash_root)
        classifier = WorkspaceResourceClassifier()
        self._reconciler = WorkspaceReconciler(
            settings=settings,
            manifest_store=manifest_store,
            classifier=classifier,
        )
        self._text_search = WorkspaceTextSearchService(settings.search)
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._settings.root

    @property
    def settings(self) -> WorkspaceSettings:
        return self._settings

    @property
    def active_day(self) -> BusinessDay | None:
        with self._lock:
            day = self._manifest_store.load().day
            return BusinessDay.parse(day) if day else None

    def initialize_day(self, day: BusinessDay) -> WorkspaceReconcileResult:
        """Claim an empty or legacy active root for one explicit business day."""

        with self._lock:
            if not isinstance(day, BusinessDay):
                raise WorkspaceContractError("Workspace day must be a BusinessDay")
            manifest = self._manifest_store.load()
            if manifest.day and manifest.day != str(day):
                raise WorkspaceInvariantError(
                    "Workspace active day mismatch: "
                    f"expected {day}, found {manifest.day}"
                )
            if not manifest.day:
                self._manifest_store.save(replace(manifest, day=str(day)))
            return self.reconcile()

    def require_day(self, day: BusinessDay) -> None:
        with self._lock:
            manifest = self._manifest_store.load()
            if not isinstance(day, BusinessDay) or manifest.day != str(day):
                raise WorkspaceInvariantError(
                    "Workspace is not initialized for the requested business day"
                )

    def archive_day(
        self,
        day: BusinessDay,
        *,
        workspace_target: Path,
        trash_target: Path,
    ) -> None:
        """Move one reconciled active day into a unified pending archive."""

        with self._lock:
            self.require_day(day)
            reconciliation = self.reconcile()
            if not reconciliation.complete:
                raise WorkspaceReconciliationError(
                    "Workspace archive requires complete reconciliation"
                )
            trash_source = self._trash_store.root
            if trash_target.exists() and trash_source.exists():
                raise WorkspaceIOError(
                    "Workspace archive has both active and archived Trash"
                )
            if not trash_target.exists():
                trash_target.parent.mkdir(parents=True, exist_ok=True)
                if trash_source.exists():
                    try:
                        os.replace(trash_source, trash_target)
                    except OSError as exc:
                        raise WorkspaceIOError(
                            f"Failed to archive Workspace Trash: {exc}"
                        ) from exc
                else:
                    trash_target.mkdir(parents=True)
            if workspace_target.exists() and self._settings.root.exists():
                raise WorkspaceIOError(
                    "Workspace archive has both active and archived roots"
                )
            if not workspace_target.exists():
                workspace_target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(self._settings.root, workspace_target)
                except OSError as exc:
                    raise WorkspaceIOError(
                        f"Failed to archive Workspace: {exc}"
                    ) from exc

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
            self._raise_trash_restore_required(link_value)
            raise WorkspaceContractError(
                f"Workspace resource does not exist: {link_value}"
            )
        current = records[index]
        if current.digest != expected_digest:
            raise WorkspaceContractError(
                f"Workspace resource digest mismatch: {link_value}"
            )
        observed = self._inspect_record(link_value)
        observed_path = self.path_for(observed.link)
        observed_bytes = self._read_rollback_bytes(observed_path)
        if sha256(observed_bytes).hexdigest() != expected_digest:
            raise WorkspaceContractError(
                f"Workspace resource changed while being described: {link_value}"
            )
        described = replace(
            current,
            description=normalized,
            described_digest=current.digest,
        )
        if described == current:
            return current
        records[index] = described
        manifest = WorkspaceManifest(
            day=reconciliation.manifest.day,
            revision=reconciliation.manifest.revision + 1,
            resources=tuple(records),
        )
        self._manifest_store.save(manifest)
        return described

    def inspect(self, link: WorkspaceLink | str) -> WorkspaceResourceRecord:
        """Inspect one disk resource without changing the manifest."""

        with self._lock:
            return self._inspect_record(link)

    def _inspect_record(
        self,
        link: WorkspaceLink | str,
        *,
        restore_if_trashed: bool = True,
    ) -> WorkspaceResourceRecord:
        path = self.path_for(link)
        if self._is_internal_path(path):
            raise WorkspaceContractError(f"Workspace resource is internal: {link}")
        if not path.exists():
            if restore_if_trashed:
                self._raise_trash_restore_required(link)
            raise WorkspaceContractError(f"Workspace resource does not exist: {link}")
        if not path.is_file():
            raise WorkspaceContractError(f"Workspace resource is not a file: {link}")
        record = self._record_for(path)
        if record is None:
            raise WorkspaceContractError(f"Workspace resource cannot be described: {link}")
        return record

    def _raise_trash_restore_required(self, link: WorkspaceLink | str) -> None:
        parsed = WorkspaceLink.parse(link) if isinstance(link, str) else link
        item = self._trash_store.latest_for_link(
            str(parsed),
            reasons=_AUTO_RESTORE_TRASH_REASONS,
        )
        if item is not None:
            raise WorkspaceTrashRestoreRequired(
                link=str(parsed),
                trash_ref=item.ref,
            )

    def read_text(
        self,
        link: WorkspaceLink | str,
        *,
        max_chars: int | None = None,
    ) -> WorkspaceTextRead:
        with self._lock:
            return self._read_text(link, max_chars=max_chars)

    def _read_text(
        self,
        link: WorkspaceLink | str,
        *,
        max_chars: int | None,
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
        with self._lock:
            return self._read_image(link, max_bytes=max_bytes)

    def _read_image(
        self,
        link: WorkspaceLink | str,
        *,
        max_bytes: int | None,
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

    def read_document(
        self,
        link: WorkspaceLink | str,
        *,
        max_bytes: int,
    ) -> WorkspaceDocumentRead:
        """Read one complete document after bounded type and digest validation."""

        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise WorkspaceContractError("Workspace document read limit must be positive")
        with self._lock:
            record = self._inspect_record(link)
            if record.kind is not WorkspaceResourceKind.DOCUMENT:
                raise WorkspaceContractError(
                    f"Workspace resource is not a document: {record.link}"
                )
            if record.size > max_bytes:
                raise WorkspaceContractError(
                    f"Workspace document exceeds the read limit: {record.link}"
                )
            path = self.path_for(record.link)
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise WorkspaceIOError(
                    f"Failed to read workspace document: {exc}"
                ) from exc
            digest = sha256(data).hexdigest()
            if len(data) > max_bytes:
                raise WorkspaceContractError(
                    f"Workspace document exceeds the read limit: {record.link}"
                )
            if len(data) != record.size or digest != record.digest:
                raise WorkspaceContractError(
                    f"Workspace document changed while being read: {record.link}"
                )
            return WorkspaceDocumentRead(
                link=record.link,
                data=data,
                media_type=record.media_type,
                suffix=record.suffix,
                size=record.size,
                digest=digest,
                retention=record.retention,
                owner_turn_id=record.owner_turn_id,
            )

    def read_text_slice(
        self,
        link: WorkspaceLink | str,
        *,
        start_line: int = 1,
        max_lines: int | None = None,
        max_chars: int | None = None,
    ) -> WorkspaceTextSlice:
        with self._lock:
            return self._read_text_slice(
                link,
                start_line=start_line,
                max_lines=max_lines,
                max_chars=max_chars,
            )

    def _read_text_slice(
        self,
        link: WorkspaceLink | str,
        *,
        start_line: int,
        max_lines: int | None,
        max_chars: int | None,
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

    def read_text_range(
        self,
        link: WorkspaceLink | str,
        *,
        start_line: int,
        end_line: int,
        cursor: int = 0,
        max_chars: int | None = None,
        expected_digest: str | None = None,
    ) -> WorkspaceTextRangeResult:
        with self._lock:
            return self._read_text_range(
                link,
                start_line=start_line,
                end_line=end_line,
                cursor=cursor,
                max_chars=max_chars,
                expected_digest=expected_digest,
            )

    def _read_text_range(
        self,
        link: WorkspaceLink | str,
        *,
        start_line: int,
        end_line: int,
        cursor: int,
        max_chars: int | None,
        expected_digest: str | None,
    ) -> WorkspaceTextRangeResult:
        for name, value in (("start_line", start_line), ("end_line", end_line)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise WorkspaceContractError(
                    f"Workspace read {name} must be a positive integer"
                )
        if end_line < start_line:
            raise WorkspaceContractError(
                "Workspace read end_line must be greater than or equal to start_line"
            )
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise WorkspaceContractError(
                "Workspace read cursor must be a non-negative integer"
            )
        if max_chars is not None and (
            isinstance(max_chars, bool)
            or not isinstance(max_chars, int)
            or max_chars <= 0
        ):
            raise WorkspaceContractError(
                "Workspace read max_chars must be a positive integer"
            )
        if expected_digest is not None and (
            not isinstance(expected_digest, str) or not expected_digest
        ):
            raise WorkspaceContractError(
                "Workspace read expected_digest must be a non-empty string"
            )
        limit = (
            self._settings.max_read_chars
            if max_chars is None
            else min(max_chars, self._settings.max_read_chars)
        )
        record = self._inspect_record(link)
        if record.kind is not WorkspaceResourceKind.TEXT:
            raise WorkspaceContractError(
                f"Workspace resource is not directly readable text: {record.link}"
            )
        if expected_digest is not None and record.digest != expected_digest:
            raise WorkspaceContractError(
                f"Workspace resource digest mismatch: {record.link}"
            )
        try:
            page = read_text_file_range(
                self.path_for(record.link),
                start_line=start_line,
                end_line=end_line,
                cursor=cursor,
                max_chars=limit,
            )
        except UnicodeDecodeError as exc:
            raise WorkspaceContractError(
                f"Workspace resource is not readable as UTF-8 text: {record.link}"
            ) from exc
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to read workspace resource: {exc}") from exc
        if not page.cursor_valid:
            raise WorkspaceContractError(
                f"Workspace read cursor exceeds the requested range: {record.link}"
            )
        return WorkspaceTextRangeResult(
            link=record.link,
            digest=record.digest,
            size=record.size,
            start_line=start_line,
            end_line=end_line,
            max_chars=limit,
            page=page,
        )

    def search_text(
        self,
        query: str,
        *,
        scope: WorkspaceSearchScope,
        case_sensitive: bool = False,
        top_k: int | None = None,
    ) -> WorkspaceTextSearchResult:
        with self._lock:
            if not isinstance(scope, WorkspaceSearchScope):
                raise WorkspaceContractError(
                    "Workspace search scope must be a WorkspaceSearchScope"
                )
            manifest = self._manifest_store.load()
            records = self._search_records(manifest, scope)
            return self._text_search.search(
                query=query,
                scope=scope,
                records=records,
                root=self._settings.root,
                case_sensitive=case_sensitive,
                top_k=top_k,
            )

    def _search_records(
        self,
        manifest: WorkspaceManifest,
        scope: WorkspaceSearchScope,
    ) -> tuple[WorkspaceResourceRecord, ...]:
        text_records = tuple(
            sorted(
                (
                    record
                    for record in manifest.resources
                    if record.kind is WorkspaceResourceKind.TEXT
                ),
                key=lambda record: record.link,
            )
        )
        if scope.kind is WorkspaceSearchScopeKind.WORKSPACE:
            return text_records
        if scope.kind is WorkspaceSearchScopeKind.FILE:
            record = next(
                (record for record in manifest.resources if record.link == scope.locator),
                None,
            )
            if record is None:
                self._raise_trash_restore_required(scope.locator)
                raise WorkspaceContractError(
                    f"Workspace search file is not in the current manifest: {scope.locator}"
                )
            if record.kind is not WorkspaceResourceKind.TEXT:
                raise WorkspaceContractError(
                    f"Workspace search file is not readable text: {scope.locator}"
                )
            return (record,)
        directory_link = WorkspaceLink.parse(scope.locator[:-1])
        directory_path = self.path_for(directory_link)
        if self._is_internal_path(directory_path):
            raise WorkspaceContractError(
                f"Workspace search directory is internal: {scope.locator}"
            )
        relative = directory_path.resolve().relative_to(self._settings.root.resolve())
        ignored = set(self._settings.ignore_dirs)
        if any(part in ignored or part.startswith(".") for part in relative.parts):
            raise WorkspaceContractError(
                f"Workspace search directory is ignored: {scope.locator}"
            )
        if not directory_path.exists() or not directory_path.is_dir():
            raise WorkspaceContractError(
                f"Workspace search directory does not exist: {scope.locator}"
            )
        prefix = directory_link.relative_path.rstrip("/") + "/"
        return tuple(
            record
            for record in text_records
            if record.relative_path.startswith(prefix)
        )

    def write_target_exists(self, link: WorkspaceLink | str) -> bool:
        with self._lock:
            return self._write_target_exists(link)

    def _write_target_exists(self, link: WorkspaceLink | str) -> bool:
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
        retention: WorkspaceRetention | None = None,
        owner_turn_id: str = "",
    ) -> WorkspaceResourceRecord:
        with self._lock:
            return self._write_text(
                link,
                text,
                overwrite=overwrite,
                expected_digest=expected_digest,
                retention=retention,
                owner_turn_id=owner_turn_id,
            )

    def _write_text(
        self,
        link: WorkspaceLink | str,
        text: str,
        *,
        overwrite: bool = False,
        expected_digest: str = "",
        retention: WorkspaceRetention | None = None,
        owner_turn_id: str = "",
    ) -> WorkspaceResourceRecord:
        if not isinstance(text, str):
            raise WorkspaceContractError("Workspace write text must be a string")
        if not isinstance(overwrite, bool):
            raise WorkspaceContractError("Workspace write overwrite must be a boolean")
        if not isinstance(expected_digest, str):
            raise WorkspaceContractError(
                "Workspace write expected_digest must be a string"
            )
        if retention is not None and not isinstance(retention, WorkspaceRetention):
            raise WorkspaceContractError(
                "Workspace write retention must be a WorkspaceRetention or None"
            )
        if not isinstance(owner_turn_id, str):
            raise WorkspaceContractError("Workspace write owner_turn_id must be a string")
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
        elif expected_digest:
            self._raise_trash_restore_required(parsed)
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
        if expected_digest and (
            previous is None or sha256(previous).hexdigest() != expected_digest
        ):
            raise WorkspaceContractError(
                f"Workspace resource digest mismatch: {parsed}"
            )
        try:
            atomic_write_text(path, text)
        except OSError as exc:
            raise WorkspaceIOError(f"Failed to write workspace resource: {exc}") from exc
        record = self._reconcile_mutation(
            path,
            link=str(parsed),
            previous=previous,
        )
        if retention is None and existed:
            return record
        return self._set_record_lifecycle(
            record,
            retention=retention or WorkspaceRetention.DAY,
            owner_turn_id=owner_turn_id,
        )

    def write_bundle(
        self,
        writes: Sequence[WorkspaceBundleWrite],
        *,
        delete_links: Sequence[WorkspaceLink | str] = (),
        expected_delete_digests: Mapping[str, str] | None = None,
    ) -> WorkspaceBundleResult:
        """Commit a multi-resource mutation with disk and manifest rollback."""

        with self._lock:
            items = tuple(writes)
            if any(not isinstance(item, WorkspaceBundleWrite) for item in items):
                raise WorkspaceContractError(
                    "Workspace bundle writes must be WorkspaceBundleWrite values"
                )
            write_links = tuple(item.link for item in items)
            if len(set(write_links)) != len(write_links):
                raise WorkspaceContractError(
                    "Workspace bundle write links must be unique"
                )
            deletes = tuple(
                WorkspaceLink.parse(link) if isinstance(link, str) else link
                for link in delete_links
            )
            delete_values = tuple(str(link) for link in deletes)
            delete_guards = dict(expected_delete_digests or {})
            if any(
                not isinstance(link, str)
                or not isinstance(digest, str)
                for link, digest in delete_guards.items()
            ):
                raise WorkspaceContractError(
                    "Workspace bundle delete digest guards must contain text values"
                )
            unknown_guards = set(delete_guards) - set(delete_values)
            if unknown_guards:
                raise WorkspaceContractError(
                    "Workspace bundle delete digest guard has no matching delete: "
                    + sorted(unknown_guards)[0]
                )
            if not items and not deletes:
                raise WorkspaceContractError(
                    "Workspace bundle requires at least one write or delete"
                )
            if len(set(delete_values)) != len(delete_values):
                raise WorkspaceContractError(
                    "Workspace bundle delete links must be unique"
                )
            overlap = set(write_links) & set(delete_values)
            if overlap:
                raise WorkspaceContractError(
                    "Workspace bundle cannot write and delete the same resource: "
                    + sorted(overlap)[0]
                )

            reconciliation = self.reconcile()
            if not reconciliation.complete:
                raise WorkspaceReconciliationError(
                    "Workspace bundle requires complete reconciliation"
                )
            original_manifest = reconciliation.manifest
            original_records = {
                record.link: record for record in original_manifest.resources
            }
            paths: dict[str, Path] = {}
            previous: dict[str, bytes | None] = {}
            for item in items:
                path = self.path_for(item.link)
                self._check_mutable_path(path, link=item.link)
                current = original_records.get(item.link)
                if path.exists() and not path.is_file():
                    raise WorkspaceContractError(
                        f"Workspace resource is not a file: {item.link}"
                    )
                if current is not None and not item.overwrite:
                    raise WorkspaceContractError(
                        f"Workspace resource already exists: {item.link}"
                    )
                if current is None and item.expected_digest:
                    raise WorkspaceContractError(
                        "Workspace resource does not exist for digest check: "
                        + item.link
                    )
                content = self._read_rollback_bytes(path) if path.exists() else None
                if item.expected_digest and (
                    content is None
                    or sha256(content).hexdigest() != item.expected_digest
                ):
                    raise WorkspaceContractError(
                        f"Workspace resource digest mismatch: {item.link}"
                    )
                paths[item.link] = path
                previous[item.link] = content

            for parsed, link in zip(deletes, delete_values, strict=True):
                path = self.path_for(parsed)
                self._check_mutable_path(path, link=link)
                current = original_records.get(link)
                if current is None or not path.is_file():
                    raise WorkspaceContractError(
                        f"Workspace bundle delete resource does not exist: {link}"
                    )
                paths[link] = path
                previous_content = self._read_rollback_bytes(path)
                previous[link] = previous_content
                expected = delete_guards.get(link, "")
                if expected and sha256(previous_content).hexdigest() != expected:
                    raise WorkspaceContractError(
                        f"Workspace bundle delete resource digest mismatch: {link}"
                    )

            try:
                for item in items:
                    atomic_write_bytes(paths[item.link], item.data)
                for link in delete_values:
                    paths[link].unlink()
                committed = self.reconcile()
                if not committed.complete:
                    raise WorkspaceReconciliationError(
                        "Workspace bundle could not complete disk reconciliation"
                    )
                records = list(committed.manifest.resources)
                by_link = {record.link: index for index, record in enumerate(records)}
                written_records: list[WorkspaceResourceRecord] = []
                for item in items:
                    index = by_link.get(item.link)
                    if index is None:
                        raise WorkspaceInvariantError(
                            "Workspace bundle record is absent after reconciliation: "
                            + item.link
                        )
                    record = records[index]
                    original = original_records.get(item.link)
                    updated = replace(
                        record,
                        retention=(
                            original.retention
                            if original is not None
                            else item.retention or WorkspaceRetention.DAY
                        ),
                        owner_turn_id=(
                            original.owner_turn_id
                            if original is not None
                            else item.owner_turn_id
                        ),
                    )
                    records[index] = updated
                    written_records.append(updated)
                final_manifest = replace(
                    committed.manifest,
                    resources=tuple(records),
                )
                if final_manifest != committed.manifest:
                    self._manifest_store.save(final_manifest)
                return WorkspaceBundleResult(
                    manifest=final_manifest,
                    records=tuple(written_records),
                )
            except (OSError, WorkspaceError) as exc:
                self._rollback_bundle(
                    paths=paths,
                    previous=previous,
                    original_manifest=original_manifest,
                    cause=exc,
                )
                if isinstance(exc, WorkspaceError):
                    raise
                raise WorkspaceIOError(
                    f"Workspace bundle mutation failed: {exc}"
                ) from exc

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
        previous = self._read_rollback_bytes(path)
        if expected_digest and sha256(previous).hexdigest() != expected_digest:
            raise WorkspaceContractError(
                f"Workspace resource digest mismatch: {record.link}"
            )
        try:
            current = previous.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceContractError(
                f"Workspace resource is not readable as UTF-8 text: {record.link}"
            ) from exc
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

    def trash_resource(
        self,
        link: WorkspaceLink | str,
        *,
        reason: str,
        source_turn_id: str = "",
    ) -> WorkspaceTrashItem:
        with self._lock:
            return self._trash_resource(
                link,
                reason=reason,
                source_turn_id=source_turn_id,
            )

    def _trash_resource(
        self,
        link: WorkspaceLink | str,
        *,
        reason: str,
        source_turn_id: str,
    ) -> WorkspaceTrashItem:
        inspected = self._inspect_record(link, restore_if_trashed=False)
        manifest_record = self._manifest_record(inspected.link)
        record = (
            manifest_record
            if manifest_record is not None
            and manifest_record.digest == inspected.digest
            else inspected
        )
        path = self.path_for(record.link)
        self._check_mutable_path(path, link=record.link)
        item = self._trash_store.prepare(
            record,
            reason=reason,
            day=self._manifest_store.load().day,
            source_turn_id=source_turn_id,
        )
        content = self._trash_store.content_path(item)
        try:
            os.replace(path, content)
        except OSError as exc:
            self._trash_store.discard(item)
            raise WorkspaceIOError(f"Failed to stage workspace trash move: {exc}") from exc
        try:
            reconciliation = self.reconcile()
            if not reconciliation.complete:
                raise WorkspaceReconciliationError(
                    "Workspace trash could not complete disk reconciliation"
                )
            self._trash_store.commit(item)
        except WorkspaceError as exc:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(content, path)
                self._trash_store.discard(item)
                self.reconcile()
                restored = self._manifest_record(record.link)
                if restored is not None:
                    self._restore_record_metadata(restored, original=record)
            except (OSError, WorkspaceError) as rollback_error:
                raise WorkspaceIOError(
                    "Workspace trash failed and rollback also failed: "
                    f"{rollback_error}"
                ) from exc
            raise
        return item

    def restore_resource(self, trash_ref: str) -> WorkspaceResourceRecord:
        with self._lock:
            item = self._trash_store.load(trash_ref)
            target = self.path_for(item.original.link)
            self._check_mutable_path(target, link=item.original.link)
            if target.exists():
                raise WorkspaceContractError(
                    f"Workspace restore target already exists: {item.original.link}"
                )
            content = self._trash_store.content_path(item)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(content, target)
            except OSError as exc:
                raise WorkspaceIOError(f"Failed to restore Workspace resource: {exc}") from exc
            try:
                reconciliation = self.reconcile()
                if not reconciliation.complete:
                    raise WorkspaceReconciliationError(
                        "Workspace restore could not complete disk reconciliation"
                    )
                record = self._inspect_record(item.original.link)
                record = self._restore_record_metadata(
                    record,
                    original=item.original,
                )
                self._trash_store.discard(item)
                return record
            except WorkspaceError as exc:
                try:
                    os.replace(target, content)
                    self.reconcile()
                except (OSError, WorkspaceError) as rollback_error:
                    raise WorkspaceIOError(
                        "Workspace restore failed and rollback also failed: "
                        f"{rollback_error}"
                    ) from exc
                raise

    def trash_items(self) -> tuple[WorkspaceTrashItem, ...]:
        with self._lock:
            return self._trash_store.list()

    def prepare_task_input(
        self,
        links: Sequence[WorkspaceLink | str],
        *,
        max_chars_per_resource: int | None = None,
    ) -> WorkspacePromptInput:
        with self._lock:
            return self._prepare_task_input(
                links,
                max_chars_per_resource=max_chars_per_resource,
            )

    def _prepare_task_input(
        self,
        links: Sequence[WorkspaceLink | str],
        *,
        max_chars_per_resource: int | None,
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

    def prepare_analysis_references(
        self,
        links: Sequence[WorkspaceLink | str],
    ) -> WorkspaceAnalysisPreparation:
        with self._lock:
            return self._prepare_analysis_references(links)

    def _prepare_analysis_references(
        self,
        links: Sequence[WorkspaceLink | str],
    ) -> WorkspaceAnalysisPreparation:
        settings = self._settings.analysis
        if not links:
            raise WorkspaceContractError(
                "Workspace analysis requires at least one reference link"
            )
        normalized = tuple(
            str(WorkspaceLink.parse(link)) if isinstance(link, str) else str(link)
            for link in links
        )
        if len(set(normalized)) != len(normalized):
            raise WorkspaceContractError(
                "Workspace analysis reference links must be unique"
            )
        if len(normalized) > settings.max_reference_links:
            return WorkspaceAnalysisPreparation(
                failure=WorkspaceAnalysisBudgetFailure(
                    reason=WorkspaceAnalysisBudgetReason.REFERENCE_COUNT,
                    limit=settings.max_reference_links,
                    observed=len(normalized),
                )
            )

        references: list[WorkspaceAnalysisReference] = []
        inspected: list[WorkspaceResourceRecord] = []
        total_chars = 0
        for index, link in enumerate(normalized, start=1):
            record = self._inspect_record(link)
            if record.kind is not WorkspaceResourceKind.TEXT:
                raise WorkspaceContractError(
                    f"Workspace analysis reference is not readable text: {record.link}"
                )
            inspected.append(record)
            try:
                read = read_text_prefix(
                    self.path_for(record.link),
                    max_chars=settings.max_chars_per_reference,
                )
            except UnicodeDecodeError as exc:
                raise WorkspaceContractError(
                    f"Workspace resource is not readable as UTF-8 text: {record.link}"
                ) from exc
            except OSError as exc:
                raise WorkspaceIOError(
                    f"Failed to read workspace analysis reference: {exc}"
                ) from exc
            if read.truncated:
                return WorkspaceAnalysisPreparation(
                    failure=WorkspaceAnalysisBudgetFailure(
                        reason=WorkspaceAnalysisBudgetReason.REFERENCE_CHARS,
                        limit=settings.max_chars_per_reference,
                        observed=settings.max_chars_per_reference + 1,
                        offending_link=record.link,
                        inspected=tuple(inspected),
                    )
                )
            proposed_total = total_chars + len(read.text)
            if proposed_total > settings.max_source_chars:
                return WorkspaceAnalysisPreparation(
                    failure=WorkspaceAnalysisBudgetFailure(
                        reason=WorkspaceAnalysisBudgetReason.SOURCE_CHARS,
                        limit=settings.max_source_chars,
                        observed=proposed_total,
                        offending_link=record.link,
                        inspected=tuple(inspected),
                    )
                )
            total_chars = proposed_total
            references.append(
                WorkspaceAnalysisReference(
                    source_id=f"source_{index}",
                    link=record.link,
                    text=read.text,
                    digest=record.digest,
                    size=record.size,
                    end_line=_text_end_line(read.text),
                )
            )
        return WorkspaceAnalysisPreparation(
            input=WorkspaceAnalysisInput(
                references=tuple(references),
                total_chars=total_chars,
            )
        )

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
            self._inspect_record(link)
            reconciliation = self.reconcile()
            if not reconciliation.complete:
                raise WorkspaceReconciliationError(
                    "Workspace mutation could not complete disk reconciliation"
                )
            record = self._manifest_record(link)
            if record is None:
                raise WorkspaceInvariantError(
                    f"Reconciled Workspace record is absent from Manifest: {link}"
                )
            return record
        except WorkspaceError as exc:
            self._rollback_mutation(path, previous=previous, cause=exc)
            raise

    def _set_record_lifecycle(
        self,
        record: WorkspaceResourceRecord,
        *,
        retention: WorkspaceRetention,
        owner_turn_id: str,
    ) -> WorkspaceResourceRecord:
        updated = replace(
            record,
            retention=retention,
            owner_turn_id=owner_turn_id,
        )
        if updated == record:
            return record
        manifest = self._manifest_store.load()
        if all(item.link != record.link for item in manifest.resources):
            raise WorkspaceInvariantError(
                f"Reconciled Workspace record is absent from Manifest: {record.link}"
            )
        self._manifest_store.save(
            WorkspaceManifest(
                day=manifest.day,
                revision=manifest.revision + 1,
                resources=tuple(
                    updated if item.link == record.link else item
                    for item in manifest.resources
                ),
            )
        )
        return updated

    def _manifest_record(self, link: str) -> WorkspaceResourceRecord | None:
        return next(
            (
                record
                for record in self._manifest_store.load().resources
                if record.link == link
            ),
            None,
        )

    def _restore_record_metadata(
        self,
        record: WorkspaceResourceRecord,
        *,
        original: WorkspaceResourceRecord,
    ) -> WorkspaceResourceRecord:
        if record.digest != original.digest:
            raise WorkspaceInvariantError(
                f"Restored Workspace resource digest changed: {record.link}"
            )
        updated = replace(
            record,
            description=original.description,
            described_digest=original.described_digest,
            retention=original.retention,
            owner_turn_id=original.owner_turn_id,
        )
        if updated == record:
            return record
        manifest = self._manifest_store.load()
        if all(item.link != record.link for item in manifest.resources):
            raise WorkspaceInvariantError(
                f"Restored Workspace record is absent from Manifest: {record.link}"
            )
        self._manifest_store.save(
            WorkspaceManifest(
                day=manifest.day,
                revision=manifest.revision + 1,
                resources=tuple(
                    updated if item.link == record.link else item
                    for item in manifest.resources
                ),
            )
        )
        return updated

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

    def _rollback_bundle(
        self,
        *,
        paths: dict[str, Path],
        previous: dict[str, bytes | None],
        original_manifest: WorkspaceManifest,
        cause: Exception,
    ) -> None:
        try:
            for link, path in reversed(tuple(paths.items())):
                content = previous[link]
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(path, content)
            self._manifest_store.save(original_manifest)
        except (OSError, WorkspaceError) as rollback_error:
            raise WorkspaceIOError(
                "Workspace bundle failed and rollback also failed: "
                f"{rollback_error}"
            ) from cause


class WorkspaceEngineBuilder:
    """Build a WorkspaceEngine from parsed settings."""

    def __init__(self, settings: WorkspaceSettings) -> None:
        self._settings = settings

    def build(self) -> WorkspaceEngine:
        if self._settings.root.exists() and not self._settings.root.is_dir():
            raise WorkspaceIOError("Workspace root must be a directory")
        trash_store = WorkspaceTrashStore(self._settings.trash_root)
        recovered = trash_store.recover_uncommitted(self._settings.root)
        engine = WorkspaceEngine(
            settings=self._settings,
            manifest_store=WorkspaceManifestStore(self._settings.manifest_path),
            trash_store=trash_store,
        )
        engine.load_manifest()
        if recovered:
            result = engine.reconcile()
            if not result.complete:
                raise WorkspaceReconciliationError(
                    "Workspace recovery could not complete disk reconciliation"
                )
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


def _text_end_line(text: str) -> int:
    if not text:
        return 0
    newline_count = text.count("\n")
    return newline_count if text.endswith("\n") else newline_count + 1
