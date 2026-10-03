"""Workspace assembly, daily lifecycle and serialized owner operations."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from threading import RLock

from tinysoul.infra.filesystem import atomic_write_text, read_text_prefix
from tinysoul.infra.json import JsonObject
from tinysoul.infra.paging import PageOptions
from tinysoul.infra.references import (
    ReferenceError,
    ReferenceResolver,
    ResourceTarget,
    markdown_references,
    relative_reference,
)
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.retrieval.contracts import (
    AttributeField,
    AttributeFilters,
    AttributeKind,
    BacklinksSource,
    ContentCoverage,
    ContentUnit,
    DirectorySource,
    EvidenceKind,
    QuerySource,
    RefsSource,
    ResourceScope,
    ResourceScopeKind,
    RetrievalRequest,
    SearchCandidate,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
    TextQuery,
)
from tinysoul.kernel.retrieval.disclosure import (
    content_units,
    fragment_range,
    range_evidence,
)
from tinysoul.kernel.retrieval.operations import SearchCorpus
from tinysoul.runtime import NullObservationEmitter, ObservationEmitter

from .config import WorkspaceSettings
from .errors import (
    WorkspaceContractError,
    WorkspaceInvariantError,
    WorkspaceIOError,
    WorkspaceNotFoundError,
    WorkspaceReconciliationError,
)
from .inspection.models import (
    WorkspaceAnalysisPreparation,
    WorkspaceBlobRead,
    WorkspaceBundleResult,
    WorkspaceBundleWrite,
    WorkspaceByteRead,
    WorkspaceDocumentRead,
    WorkspaceImageRead,
    WorkspacePromptInput,
    WorkspaceTextRangeResult,
    WorkspaceTextRead,
)
from .inspection.reader import WorkspaceReader
from .links import WorkspaceLink
from .storage.manifest import (
    WorkspaceManifest,
    WorkspaceManifestStore,
    WorkspaceResourceKind,
    WorkspaceResourceRecord,
    WorkspaceTag,
)
from .storage.mutations import WorkspaceMutations, WorkspaceTextEdit
from .storage.reconcile import WorkspaceReconciler, WorkspaceReconcileResult
from .storage.trash import WorkspaceTrashItem, WorkspaceTrashStore

WORKSPACE_SEARCH_FILTERS = AttributeFilters(
    (
        AttributeField("tags", AttributeKind.TEXT_SET),
        AttributeField("file_type"),
        AttributeField("day", AttributeKind.DATE),
        AttributeField("kind"),
    )
)
from .events import (
    WORKSPACE_OWNER,
    WORKSPACE_WATCH,
    WorkspaceChange,
    WorkspaceChangeOperation,
    WorkspaceEvents,
)
from .observation import emit_workspace_changed


@dataclass(frozen=True)
class WorkspaceExecutionLocation:
    """Physical locations granted only to the execution plugin."""

    cwd: Path
    capture_root: Path
    script_path: Path | None
    links: tuple[str, ...]


@dataclass(frozen=True)
class WorkspaceArchiveView:
    """Fixed metadata and bounded read-only access to archived resources."""

    root: Path
    manifest: WorkspaceManifest
    max_read_chars: int

    @property
    def day(self) -> str:
        return self.manifest.day

    def reader(self) -> WorkspaceReader:
        settings = WorkspaceSettings(root=self.root, max_read_chars=self.max_read_chars)
        discovery = WorkspaceReconciler(
            settings=settings,
            manifest_store=WorkspaceManifestStore(settings.manifest_path),
        )

        def inspect(link: str) -> WorkspaceResourceRecord:
            record = next(
                (item for item in self.manifest.resources if item.link == link), None
            )
            if record is None:
                raise WorkspaceNotFoundError("Archived Workspace resource is absent")
            return record

        return WorkspaceReader(
            settings=settings, inspect=inspect, path_for=discovery.path_for
        )

    def browse_text(
        self, link: str, *, page: PageOptions = PageOptions(), full: bool = False
    ) -> JsonObject:
        return self.reader().browse_text(
            link, day=self.day, page=page, full=full, editable=False
        )

    def open_blob(self, link: str) -> WorkspaceBlobRead:
        return self.reader().open_blob(link)

    def trash_items(self) -> tuple[WorkspaceTrashItem, ...]:
        return WorkspaceTrashStore(self.root.parent / "trash").list()

    def read_text(
        self, link: str, *, max_chars: int | None = None
    ) -> WorkspaceTextRead:
        limit = self.max_read_chars if max_chars is None else max_chars
        if type(limit) is not int or not 0 < limit <= self.max_read_chars:
            raise WorkspaceContractError("Archived Workspace read bound is invalid")
        return self.reader().read_text(link, max_chars=limit)


class WorkspaceEngine:
    """Single owner of current-day files, metadata, Trash and publication."""

    def __init__(
        self,
        *,
        settings: WorkspaceSettings,
        manifest_store: WorkspaceManifestStore,
        trash_store: WorkspaceTrashStore | None = None,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._settings = settings
        self._manifest_store = manifest_store
        self._trash_store = trash_store or WorkspaceTrashStore(settings.trash_root)
        self._observations = observations or NullObservationEmitter()
        self._lock = RLock()
        self.events = WorkspaceEvents()
        self._reconciler = WorkspaceReconciler(
            settings=settings, manifest_store=manifest_store
        )
        self._reader = WorkspaceReader(
            settings=settings, inspect=self.inspect, path_for=self.path_for
        )
        self._mutations = WorkspaceMutations(
            settings=settings,
            store=manifest_store,
            discovery=self._reconciler,
            trash=self._trash_store,
            lock=self._lock,
        )

    @property
    def root(self) -> Path:
        return self._settings.root

    @property
    def settings(self) -> WorkspaceSettings:
        return self._settings

    @property
    def active_day(self) -> CalendarDay | None:
        with self._lock:
            day = self._manifest_store.load().day
            return CalendarDay.parse(day) if day else None

    def initialize_day(self, day: CalendarDay) -> WorkspaceReconcileResult:
        """Bind a valid unassigned active root to one explicit calendar day."""

        with self._lock:
            before = self._manifest_store.load()
            if not isinstance(day, CalendarDay):
                raise WorkspaceContractError("Workspace day must be a CalendarDay")
            manifest = self._manifest_store.load()
            if manifest.day and manifest.day != str(day):
                raise WorkspaceInvariantError(
                    "Workspace active day mismatch: "
                    f"expected {day}, found {manifest.day}"
                )
            if not manifest.day:
                self._manifest_store.save(replace(manifest, day=str(day)))
            result = self._reconciler.reconcile()
        self._emit_change(
            operation=WorkspaceChangeOperation.INITIALIZE,
            before=before,
            after=result.manifest,
        )
        return result

    def require_day(self, day: CalendarDay) -> None:
        with self._lock:
            manifest = self._manifest_store.load()
            if not isinstance(day, CalendarDay) or manifest.day != str(day):
                raise WorkspaceInvariantError(
                    "Workspace is not initialized for the requested business day"
                )

    def archive_day(
        self,
        day: CalendarDay,
        *,
        workspace_target: Path,
        trash_target: Path,
    ) -> None:
        """Move one reconciled active day into a unified pending archive."""

        with self._lock:
            self.require_day(day)
            reconciliation = self._reconciler.reconcile()
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
                try:
                    trash_target.parent.mkdir(parents=True, exist_ok=True)
                    if trash_source.exists():
                        os.replace(trash_source, trash_target)
                    else:
                        trash_target.mkdir(parents=True)
                except OSError as exc:
                    raise WorkspaceIOError(
                        "Workspace Trash cannot be archived"
                    ) from exc
            if workspace_target.exists() and self._settings.root.exists():
                raise WorkspaceIOError(
                    "Workspace archive has both active and archived roots"
                )
            if not workspace_target.exists():
                try:
                    workspace_target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(self._settings.root, workspace_target)
                except OSError as exc:
                    raise WorkspaceIOError("Workspace cannot be archived") from exc

    def path_for(self, link: WorkspaceLink | str) -> Path:
        return self._reconciler.path_for(link)

    def resolve_relative(self, reference: str, origin_link: str) -> str:
        origin = WorkspaceLink.parse(origin_link.partition("#")[0])
        return relative_reference(
            reference, source_path=origin.relative_path, prefix="workspace:"
        )

    def load_manifest(self) -> WorkspaceManifest:
        with self._lock:
            return self._manifest_store.load()

    def inspect(self, link: str) -> WorkspaceResourceRecord:
        with self._lock:
            previous = next(
                (
                    item
                    for item in self._manifest_store.load().resources
                    if item.link == link
                ),
                None,
            )
            return self._reconciler.inspect_record(self.path_for(link), previous)

    def write_target_exists(self, link: str) -> bool:
        with self._lock:
            return self.path_for(link).exists()

    def prepare_external_cwd(
        self, connection_id: str, *, cwd_link: str = ""
    ) -> tuple[Path, str]:
        """Resolve an existing explicit cwd, or create an isolated Agent directory."""
        if re.fullmatch(r"connection_[0-9a-f]{32}", connection_id) is None:
            raise WorkspaceContractError("External connection identity is invalid")
        link = cwd_link or f"workspace:connections/{connection_id}"
        with self._lock:
            if link == "workspace:":
                return self._settings.root, link
            path = self.path_for(link)
            if cwd_link:
                if not path.is_dir():
                    raise WorkspaceContractError(
                        "External Agent cwd must be an existing directory"
                    )
            else:
                self.mkdir(link)
            return path, link

    def prepare_execution(
        self,
        job_id: str,
        *,
        cwd_link: str = "",
        source_text: str | None = None,
        source_suffix: str = "",
    ) -> WorkspaceExecutionLocation:
        """Create one Job's output area in the actual daily Workspace."""
        if (
            not isinstance(job_id, str)
            or re.fullmatch(r"job_[0-9a-f]{32}", job_id) is None
        ):
            raise WorkspaceContractError("Execution requires a valid Job identity")
        if not isinstance(cwd_link, str):
            raise WorkspaceContractError("Execution cwd must be a Workspace Link")
        if source_text is not None and (
            not isinstance(source_text, str)
            or source_suffix not in {".py", ".sh", ".ps1", ".cmd"}
        ):
            raise WorkspaceContractError("Execution source is invalid")
        with self._lock:
            prefix = f"workspace:jobs/{job_id}"
            job_root = self.path_for(prefix)
            cwd = (
                (
                    self._settings.root
                    if cwd_link == "workspace:"
                    else self.path_for(cwd_link)
                )
                if cwd_link
                else job_root
            )
            for target in (job_root, cwd):
                relative = target.relative_to(self._settings.root)
                current = self._settings.root
                for part in relative.parts:
                    current = current / part
                    if (
                        part == ".tinysoul"
                        or current.is_symlink()
                        or current.is_junction()
                    ):
                        raise WorkspaceContractError(
                            "Execution path crosses an internal or redirected directory"
                        )
            if cwd_link and not cwd.is_dir():
                raise WorkspaceContractError(
                    "Execution cwd must be an existing Workspace directory"
                )
            script_path: Path | None = None
            try:
                job_root.mkdir(parents=True, exist_ok=False)
                if source_text is not None:
                    script_path = job_root / f"source{source_suffix}"
                    atomic_write_text(script_path, source_text)
            except (OSError, UnicodeError) as exc:
                raise WorkspaceIOError(
                    "Workspace execution area could not be prepared"
                ) from exc
            return WorkspaceExecutionLocation(
                cwd=cwd,
                capture_root=job_root / "logs",
                script_path=script_path,
                links=(
                    prefix,
                    f"{prefix}/logs/stdout.log",
                    f"{prefix}/logs/stderr.log",
                ),
            )

    def snapshot(self) -> WorkspaceManifest:
        """Return the persisted state used for Context synchronization."""

        return self.load_manifest()

    def archive_snapshot(
        self,
        day: CalendarDay,
        *,
        root: Path,
    ) -> WorkspaceManifest:
        """Load one archived Workspace manifest through the owner boundary."""

        return self.archive_view(day, root=root).manifest

    def archive_view(
        self,
        day: CalendarDay,
        *,
        root: Path,
    ) -> WorkspaceArchiveView:
        """Open a narrow read-only view through the Workspace owner."""

        if not isinstance(day, CalendarDay):
            raise WorkspaceContractError("Workspace archive day is invalid")
        if not isinstance(root, Path) or not root.is_absolute():
            raise WorkspaceContractError(
                "Workspace archive root must be an absolute path"
            )
        manifest = WorkspaceManifestStore(
            root / ".tinysoul" / "workspace_manifest.json"
        ).load()
        if manifest.day != str(day):
            raise WorkspaceInvariantError(
                f"Workspace archive day mismatch: {manifest.day} != {day}"
            )
        return WorkspaceArchiveView(
            root=root.resolve(),
            manifest=manifest,
            max_read_chars=self._settings.max_read_chars,
        )

    def reconcile(self) -> WorkspaceReconcileResult:
        return self._change(
            WorkspaceChangeOperation.RECONCILE, self._reconciler.reconcile
        )

    def reconcile_external(self) -> WorkspaceReconcileResult:
        return self._change(
            WorkspaceChangeOperation.RECONCILE,
            self._reconciler.reconcile,
            source=WORKSPACE_WATCH,
        )

    def watches_path(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.root)
            return (
                bool(relative.parts)
                and not any(
                    part in self.settings.ignore_dirs or part == ".tinysoul"
                    for part in relative.parts
                )
                and not self._reconciler.is_internal_path(path)
                and not (path.name.startswith(".") and path.name.endswith(".tmp"))
            )
        except ValueError:
            return False

    def read_text(
        self, link: str, *, max_chars: int | None = None
    ) -> WorkspaceTextRead:
        with self._lock:
            return self._reader.read_text(link, max_chars=max_chars)

    def read_bytes(self, link: str, *, max_bytes: int) -> WorkspaceByteRead:
        with self._lock:
            return self._reader.read_bytes(link, max_bytes=max_bytes)

    def browse_text(
        self, link: str, *, page: PageOptions = PageOptions(), full: bool = False
    ) -> JsonObject:
        with self._lock:
            return self._reader.browse_text(
                link, day=str(self.active_day), page=page, full=full
            )

    def open_blob(self, link: str) -> WorkspaceBlobRead:
        with self._lock:
            return self._reader.open_blob(link)

    def read_image(
        self, link: str, *, max_bytes: int | None = None
    ) -> WorkspaceImageRead:
        with self._lock:
            return self._reader.read_image(link, max_bytes=max_bytes)

    def read_document(self, link: str, *, max_bytes: int) -> WorkspaceDocumentRead:
        with self._lock:
            return self._reader.read_document(link, max_bytes=max_bytes)

    def read_text_range(
        self,
        link: str,
        *,
        start_line: int,
        end_line: int,
        cursor: int = 0,
        max_chars: int | None = None,
    ) -> WorkspaceTextRangeResult:
        with self._lock:
            return self._reader.read_text_range(
                link,
                start_line=start_line,
                end_line=end_line,
                cursor=cursor,
                max_chars=max_chars,
            )

    def prepare_task_input(
        self, links: Sequence[str], *, max_chars_per_resource: int | None = None
    ) -> WorkspacePromptInput:
        with self._lock:
            return self._reader.prepare_task_input(
                links, max_chars_per_resource=max_chars_per_resource
            )

    def prepare_analysis_references(
        self, links: Sequence[str]
    ) -> WorkspaceAnalysisPreparation:
        with self._lock:
            return self._reader.prepare_analysis_references(links)

    def canonical_reference(
        self, resource: str, fragment: str = "", source_day: date | None = None
    ) -> ResourceTarget:
        try:
            link = WorkspaceLink.parse(resource)
        except WorkspaceContractError as exc:
            raise ReferenceError("Invalid Workspace reference") from exc
        day = self.active_day
        return ResourceTarget(
            str(link), fragment, source_day or (day.value if day else None)
        )

    def retrieval_corpus(
        self,
        request: RetrievalRequest,
        *,
        references: ReferenceResolver,
    ) -> SearchCorpus:
        source = request.source
        if not isinstance(
            source, (QuerySource, DirectorySource, RefsSource, BacklinksSource)
        ):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Unsupported Workspace source"
            )
        scope_value = getattr(
            source, "scope", ResourceScope(ResourceScopeKind.WORKSPACE, "")
        )
        if not isinstance(scope_value, ResourceScope):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                "Workspace source requires a resource scope",
            )
        locator = scope_value.locator
        if locator:
            WorkspaceLink.parse(locator.rstrip("/"))
        predicates = WORKSPACE_SEARCH_FILTERS.parse(getattr(source, "where", {}))
        excluded = set()
        for ref in request.exclude_refs:
            resource, _, fragment = ref.partition("#")
            excluded.add((str(WorkspaceLink.parse(resource)), fragment))
        seeds: dict[str, list[tuple[str, str]]] | None = None
        if isinstance(source, RefsSource):
            seeds = {}
            for ref in source.refs:
                resource, _, fragment = ref.partition("#")
                canonical = str(WorkspaceLink.parse(resource))
                if (canonical, fragment) in excluded:
                    continue
                pair = (canonical + ("#" + fragment if fragment else ""), fragment)
                if pair not in seeds.setdefault(canonical, []):
                    seeds[canonical].append(pair)
        if isinstance(source, QuerySource) and not isinstance(source.query, TextQuery):
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST, "Workspace query requires text"
            )
        query = (
            source.query.text
            if isinstance(source, QuerySource) and isinstance(source.query, TextQuery)
            else ""
        )
        anchor = (
            references.resolve(source.anchor_ref)
            if isinstance(source, BacklinksSource)
            else None
        )
        with self._lock:
            snapshot = self.reconcile()
            if not snapshot.complete:
                raise WorkspaceReconciliationError(
                    "Workspace retrieval requires complete discovery"
                )
            records = snapshot.manifest.resources
            if seeds is not None and set(seeds) - {record.link for record in records}:
                raise SearchFailure(
                    SearchFailureKind.INVALID_REQUEST, "Workspace ref is unavailable"
                )
            remaining = self.settings.search.max_scan_chars
            scanned, complete = 0, True
            candidates: list[SearchCandidate] = []
            day = self.active_day
            for record in records:
                if seeds is not None and record.link not in seeds:
                    continue
                if seeds is None and (record.link, "") in excluded:
                    continue
                if locator and not (
                    record.link.startswith(locator.rstrip("/") + "/")
                    if scope_value.kind is ResourceScopeKind.DIRECTORY
                    else record.link == locator
                ):
                    continue
                if anchor is not None and (
                    record.suffix.lower() not in {".md", ".markdown"}
                    or record.kind is not WorkspaceResourceKind.TEXT
                ):
                    continue
                attributes: JsonObject = {
                    "tags": [tag.value for tag in record.tags],
                    "file_type": record.suffix,
                    "day": str(day) if day else None,
                    "kind": record.kind.value,
                }
                if not all(predicate.matches(attributes) for predicate in predicates):
                    continue
                coverage = ContentCoverage.FULL
                if record.kind is WorkspaceResourceKind.TEXT:
                    if remaining <= 0:
                        complete = False
                        break
                    try:
                        read = read_text_prefix(
                            self.path_for(record.link), max_chars=remaining
                        )
                    except (OSError, UnicodeError) as exc:
                        raise WorkspaceIOError(
                            "Workspace search source cannot be read"
                        ) from exc
                    text = read.text
                    remaining -= len(text)
                    if read.truncated:
                        coverage = ContentCoverage.EXCERPT
                        if not isinstance(source, DirectorySource):
                            complete = False
                else:
                    if isinstance(source, QuerySource):
                        continue
                    text = record.description or record.relative_path
                    coverage = ContentCoverage.METADATA
                scanned += 1
                if seeds is not None:
                    for ref, fragment in seeds[record.link]:
                        if coverage is ContentCoverage.METADATA:
                            if fragment:
                                raise SearchFailure(
                                    SearchFailureKind.INVALID_REQUEST,
                                    "Non-text resource has no text fragment",
                                )
                            units = (
                                ContentUnit(record.link, record.link, text, "metadata"),
                            )
                        else:
                            first, last = fragment_range(text, fragment)
                            selected = "".join(
                                text.splitlines(keepends=True)[first - 1 : last]
                            )
                            units = content_units(
                                record.link, selected, first_line=first
                            )
                        candidates.append(
                            SearchCandidate(
                                ref,
                                record.relative_path,
                                units,
                                attributes,
                                content_coverage=coverage,
                            )
                        )
                    continue
                units = (
                    (ContentUnit(record.link, record.link, text, "metadata"),)
                    if coverage is ContentCoverage.METADATA
                    else content_units(record.link, text)
                )
                evidence: list[SearchEvidence] = []
                if anchor is not None:
                    lines = text.splitlines(keepends=True)
                    for reference in markdown_references(text):
                        try:
                            target = references.resolve(
                                relative_reference(
                                    reference.target,
                                    source_path=record.relative_path,
                                    prefix="workspace:",
                                ),
                                source_day=day.value if day else None,
                            )
                        except ReferenceError:
                            continue
                        if target.matches(anchor):
                            start = sum(
                                len(line) for line in lines[: reference.line - 1]
                            )
                            evidence.extend(
                                range_evidence(
                                    units,
                                    start,
                                    start + len(lines[reference.line - 1]),
                                    kind=EvidenceKind.REFERENCE,
                                    relation="markdown_link",
                                )
                            )
                    if not evidence:
                        continue
                candidates.append(
                    SearchCandidate(
                        record.link,
                        record.relative_path,
                        units,
                        attributes,
                        tuple(evidence),
                        coverage,
                    )
                )
            if isinstance(source, RefsSource):
                order = {
                    ref: index for index, ref in enumerate(dict.fromkeys(source.refs))
                }
                candidates.sort(key=lambda item: order.get(item.ref, len(order)))
            return SearchCorpus(tuple(candidates), query, scanned, complete)

    def write_text(
        self, link: str, text: str, *, overwrite: bool = False
    ) -> WorkspaceResourceRecord:
        return self._change(
            WorkspaceChangeOperation.WRITE,
            lambda: self._mutations.write_text(link, text, overwrite=overwrite),
        )

    def write_bundle(
        self,
        writes: Sequence[WorkspaceBundleWrite],
        *,
        delete_links: Sequence[str] = (),
    ) -> WorkspaceBundleResult:
        return self._change(
            WorkspaceChangeOperation.BUNDLE,
            lambda: self._mutations.write_bundle(writes, delete_links=delete_links),
        )

    def append_text(self, link: str, text: str) -> WorkspaceResourceRecord:
        return self._change(
            WorkspaceChangeOperation.APPEND,
            lambda: self._mutations.append_text(link, text),
        )

    def edit_text(
        self, link: str, edits: Sequence[WorkspaceTextEdit]
    ) -> WorkspaceResourceRecord:
        return self._change(
            WorkspaceChangeOperation.EDIT,
            lambda: self._mutations.edit_text(link, edits),
        )

    def mkdir(self, link: str) -> WorkspaceResourceRecord:
        return self._change(
            WorkspaceChangeOperation.MKDIR, lambda: self._mutations.mkdir(link)
        )

    def move(self, link: str, target_link: str) -> WorkspaceResourceRecord:
        return self._change(
            WorkspaceChangeOperation.MOVE,
            lambda: self._mutations.move(link, target_link),
        )

    def tag(self, link: str, tags: tuple[WorkspaceTag, ...]) -> WorkspaceResourceRecord:
        return self._change(
            WorkspaceChangeOperation.TAG, lambda: self._mutations.tag(link, tags)
        )

    def set_description(self, link: str, description: str) -> WorkspaceResourceRecord:
        return self._change(
            WorkspaceChangeOperation.DESCRIBE,
            lambda: self._mutations.set_description(link, description),
        )

    def trash_resource(self, link: str) -> WorkspaceTrashItem:
        return self._change(
            WorkspaceChangeOperation.TRASH, lambda: self._mutations.trash_resource(link)
        )

    def restore_resource(self, ref: str) -> WorkspaceResourceRecord:
        return self._change(
            WorkspaceChangeOperation.RESTORE,
            lambda: self._mutations.restore_resource(ref),
        )

    def trash_items(self) -> tuple[WorkspaceTrashItem, ...]:
        with self._lock:
            return self._trash_store.list()

    def _change[T](
        self,
        operation: WorkspaceChangeOperation,
        mutation: Callable[[], T],
        *,
        source: str = WORKSPACE_OWNER,
    ) -> T:
        with self._lock:
            before = self._manifest_store.load()
            result = mutation()
            after = self._manifest_store.load()
            written_links: tuple[str, ...] = ()
            if isinstance(result, WorkspaceBundleResult):
                written_links = tuple(record.link for record in result.records)
            elif operation in (
                WorkspaceChangeOperation.WRITE, WorkspaceChangeOperation.APPEND,
                WorkspaceChangeOperation.EDIT,
            ) and isinstance(result, WorkspaceResourceRecord):
                written_links = (result.link,)
            change = WorkspaceChange(operation, before, after, written_links)
            self.events.stage(change, source)
        emit_workspace_changed(self._observations, change=change)
        return result

    def _emit_change(
        self,
        *,
        operation: WorkspaceChangeOperation,
        before: WorkspaceManifest,
        after: WorkspaceManifest,
    ) -> None:
        change = WorkspaceChange(operation, before, after)
        self.events.stage(change)
        emit_workspace_changed(self._observations, change=change)


class WorkspaceEngineBuilder:
    def __init__(
        self,
        settings: WorkspaceSettings,
        *,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._settings, self._observations = settings, observations

    def build(self) -> WorkspaceEngine:
        if self._settings.root.exists() and not self._settings.root.is_dir():
            raise WorkspaceIOError("Workspace root must be a directory")
        engine = WorkspaceEngine(
            settings=self._settings,
            manifest_store=WorkspaceManifestStore(self._settings.manifest_path),
            observations=self._observations,
        )
        engine.load_manifest()
        return engine
