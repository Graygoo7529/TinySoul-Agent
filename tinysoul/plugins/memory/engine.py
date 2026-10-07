"""Memory owner facade for active memory and persistent five-kind documents."""

from __future__ import annotations

import secrets
from datetime import date
from pathlib import Path
from threading import RLock

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
    DocumentQuery,
    EvidenceKind,
    QuerySource,
    RefsSource,
    RetrievalRequest,
    SearchCandidate,
    SearchEvidence,
    SearchFailure,
    SearchFailureKind,
)
from tinysoul.kernel.retrieval.disclosure import (
    DisclosureHint,
    InspectPage,
    content_units,
    fragment_range,
    inspect_document,
    range_evidence,
)
from tinysoul.kernel.retrieval.engine import VectorSource
from tinysoul.kernel.retrieval.operations import SearchCorpus
from tinysoul.prompts.plugins import memory as prompt_text

from .config import MemorySettings
from .documents import (
    DailyMemoryDocument,
    MemoryDocumentCodec,
    PersistentMemoryDocument,
    StoredMemoryDocument,
)
from .errors import MemoryContractError, MemoryInvariantError
from .refs import MemoryKind, MemoryRef
from .retrieval import (
    MemoryCatalog,
    MemoryCatalogSnapshot,
    resolve_redirect,
)
from .retrieval.models import MemoryCatalogEntry
from .storage.active import (
    ActiveMemoryDocument,
    ActiveMemoryStore,
    MemoryPatchOperation,
)
from .storage.persistent import MemoryStore

MEMORY_SEARCH_FILTERS = AttributeFilters(
    (
        AttributeField("kind"),
        AttributeField("status"),
        AttributeField("updated_on", AttributeKind.DATE),
        AttributeField("confidence"),
    )
)


class MemoryEngine:
    """Single assembly facade for Memory reads, writes, retrieval, and lifecycle."""

    def __init__(
        self,
        *,
        settings: MemorySettings,
        active_session_root: Path | None = None,
        embedding: VectorSource | None = None,
    ) -> None:
        if not isinstance(settings, MemorySettings):
            raise MemoryContractError("Memory settings are invalid")
        self._settings = settings
        self._codec = MemoryDocumentCodec()
        self._store = MemoryStore(
            root=settings.root, settings=settings.documents, codec=self._codec
        )
        self.embedding = embedding
        self._catalog = MemoryCatalog(
            store=self._store,
            redirect_max_hops=settings.documents.redirect_max_hops,
        )
        self._active = (
            ActiveMemoryStore(
                session_root=active_session_root,
                max_chars=settings.max_active_chars,
            )
            if active_session_root is not None
            else None
        )
        self._lock = RLock()
        self._catalog.rebuild()

    @property
    def root(self) -> Path:
        return self._store.root

    @property
    def settings(self) -> MemorySettings:
        return self._settings

    @property
    def catalog_snapshot(self) -> MemoryCatalogSnapshot:
        return self._catalog.snapshot

    @property
    def active_session_root(self) -> Path | None:
        return self._active.session_root if self._active is not None else None

    def bind_active_session_root(self, session_root: Path) -> None:
        self._active = ActiveMemoryStore(
            session_root=session_root,
            max_chars=self._settings.max_active_chars,
        )

    def initialize_active_day(self, day: date | CalendarDay) -> ActiveMemoryDocument:
        return self._require_active().initialize_day(_date(day))

    def active_day(self) -> CalendarDay:
        return CalendarDay(self._require_active().read().day)

    def read_active(
        self, day: date | CalendarDay | None = None
    ) -> ActiveMemoryDocument:
        return self._require_active().read(
            expected_day=_date(day) if day is not None else None
        )

    def validate_active_day(self, day: date | CalendarDay) -> ActiveMemoryDocument:
        return self.read_active(day)

    def patch_active(
        self,
        *,
        day: date | CalendarDay,
        operations: tuple[MemoryPatchOperation, ...],
    ) -> ActiveMemoryDocument:
        return self._require_active().patch(
            day=_date(day),
            operations=operations,
        )

    def read_archived_active(
        self, day: date | CalendarDay, session_archive_root: Path
    ) -> ActiveMemoryDocument:
        return ActiveMemoryStore(
            session_root=session_archive_root,
            max_chars=self._settings.max_active_chars,
        ).read(expected_day=_date(day))

    def archived_active_available(
        self,
        day: date | CalendarDay,
        session_archive_root: Path,
    ) -> bool:
        target = session_archive_root / "Memory.md"
        if target.is_symlink():
            raise MemoryInvariantError("Archived active Memory cannot be a symlink")
        if not target.exists():
            return False
        if not target.is_file():
            raise MemoryInvariantError("Archived active Memory is not a file")
        self.read_archived_active(day, session_archive_root)
        return True

    def validate_archived_active(
        self, day: date | CalendarDay, session_archive_root: Path
    ) -> ActiveMemoryDocument:
        return self.read_archived_active(day, session_archive_root)

    def refs(
        self,
        *,
        kinds: tuple[MemoryKind, ...] | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[MemoryRef, ...]:
        result = tuple(self._catalog.snapshot.entries)
        if kinds:
            result = tuple(ref for ref in result if ref.kind in kinds)
        if statuses:
            result = tuple(
                ref
                for ref in result
                if self._catalog.snapshot.require(ref).status in statuses
            )
        return tuple(sorted(result, key=str))

    def browse_catalog(
        self,
        *,
        kind: str | None = None,
        query: str | None = None,
        page: PageOptions = PageOptions(),
    ) -> JsonObject:
        if kind is not None and kind not in {item.value for item in MemoryKind}:
            raise MemoryContractError("Unknown persistent Memory kind")
        with self._lock:
            values: tuple[JsonObject, ...] = tuple(
                {
                    "ref": str(item.ref),
                    "kind": item.ref.kind.value,
                    "display": item.display,
                    "status": item.status,
                    "redirect_to": str(item.redirect_to) if item.redirect_to else None,
                    "locator": {"ref": str(item.ref)},
                }
                for item in sorted(
                    self._catalog.snapshot.entries.values(),
                    key=lambda item: str(item.ref),
                )
                if (kind is None or item.ref.kind.value == kind)
                and (
                    query is None
                    or query.casefold() in f"{item.ref} {item.display}".casefold()
                )
            )
            return page.render(values, owner="memory", ref=f"catalog:{kind}:{query}")

    def browse_active(
        self,
        day: CalendarDay,
        *,
        archive_root: Path | None = None,
        page: PageOptions = PageOptions(),
    ) -> JsonObject:
        document = (
            self.read_archived_active(day, archive_root)
            if archive_root
            else self.read_active(day)
        )
        return inspect_document(
            owner="memory.active",
            ref=f"memory:current@{day}",
            text=document.content,
            direct_refs=tuple(
                DisclosureHint(
                    item.target,
                    item.label or "Referenced resource",
                    f"Line {item.line}",
                )
                for item in markdown_references(document.content)
            ),
            continuation=page.continuation,
            max_chars=page.max_chars,
            metadata={
                "day": str(day),
                "locator": {"ref": "memory:current", "day": str(day)},
            },
        ).to_json()

    def canonical_reference(
        self, resource: str, fragment: str = "", source_day: date | None = None
    ) -> ResourceTarget:
        try:
            ref = MemoryRef.from_resource(resource)
            chain = resolve_redirect(
                self._catalog.snapshot,
                ref,
                max_hops=self._settings.documents.redirect_max_hops,
            )
            return ResourceTarget(str(chain[-1]), fragment)
        except MemoryContractError as exc:
            raise ReferenceError(
                "Memory reference is not a readable persistent identity"
            ) from exc

    def resolve_relative(self, reference: str, origin_ref: str) -> str:
        origin = MemoryRef.from_resource(origin_ref.partition("#")[0])
        return relative_reference(
            reference, source_path=origin.relative_path, prefix="memory:"
        )

    def inspect(
        self,
        ref: str,
        *,
        view: str = "content",
        continuation: str | None = None,
        max_chars: int | None = None,
    ) -> InspectPage:
        resource, _, fragment = ref.partition("#")
        resource = MemoryRef.from_resource(resource)
        stored = self._store.read(resource)
        chain = resolve_redirect(
            self._catalog.snapshot,
            resource,
            max_hops=self._settings.documents.redirect_max_hops,
        )
        if max_chars is not None and (type(max_chars) is not int or max_chars < 512):
            raise MemoryContractError("Inspect max_chars must be at least 512")
        navigation: dict[str, DisclosureHint] = {}
        for target, kind, title, evidence in self._navigation_refs(
            self._catalog.snapshot.require(resource)
        ):
            if target not in navigation or kind == "markdown_reference":
                navigation[target] = DisclosureHint(target, title, evidence[:240])
        direct_refs = tuple(navigation.values())
        return inspect_document(
            owner="memory",
            ref=ref,
            text=stored.text,
            direct_refs=direct_refs,
            view=view,
            continuation=continuation,
            max_chars=min(
                max_chars or self._settings.inspect.page_max_chars,
                self._settings.inspect.page_max_chars,
            ),
            metadata={
                "kind": resource.kind.value,
                "status": stored.document.status.value,
                "display": stored.document.display,
                "resolution_chain": [str(item) for item in chain],
                "locator": {"ref": str(resource)},
            },
        )

    def search_corpus(
        self, request: RetrievalRequest, *, references: ReferenceResolver
    ) -> SearchCorpus:
        source = request.source
        snapshot = self._catalog.snapshot
        scope = getattr(source, "scope", "all")
        if scope not in {"all", *(kind.value for kind in MemoryKind)}:
            raise SearchFailure(
                SearchFailureKind.INVALID_REQUEST,
                prompt_text.INVALID_MEMORY_SCOPE,
            )
        predicates = MEMORY_SEARCH_FILTERS.parse(getattr(source, "where", {}))

        def identity(ref: str) -> tuple[str, str]:
            resource, _, fragment = ref.partition("#")
            try:
                return str(MemoryRef.from_resource(resource)), fragment
            except MemoryContractError as exc:
                raise ReferenceError(
                    "Memory search requires a persistent identity"
                ) from exc

        # Exclusions normalize syntax without requiring the target to still exist.
        excluded = {identity(ref) for ref in request.exclude_refs}
        seeds: dict[str, list[tuple[str, str]]] = {}
        seed_order: dict[str, int] = {}
        if isinstance(source, RefsSource):
            for ref in source.refs:
                canonical, fragment = identity(ref)
                if (canonical, fragment) in excluded:
                    continue
                if MemoryRef.parse(canonical) not in snapshot.entries:
                    raise ReferenceError("Memory search reference does not exist")
                selected_ref = canonical + ("#" + fragment if fragment else "")
                seed_order.setdefault(selected_ref, len(seed_order))
                pair = (selected_ref, fragment)
                if pair not in seeds.setdefault(canonical, []):
                    seeds[canonical].append(pair)
        query, query_ref = "", None
        if isinstance(source, QuerySource):
            if isinstance(source.query, DocumentQuery):
                query_ref = self.canonical_reference(source.query.document_ref).resource
                query = self._store.read(MemoryRef.parse(query_ref)).text
            else:
                query = source.query.text
        anchor = (
            references.resolve(source.anchor_ref)
            if isinstance(source, BacklinksSource)
            else None
        )
        entries = list(snapshot.entries.items())
        candidates: list[SearchCandidate] = []
        scanned = 0
        for resource, entry in entries:
            ref = str(resource)
            attributes: JsonObject = {
                "kind": resource.kind.value,
                "status": entry.status,
                "updated_on": entry.updated_on.isoformat(),
                "confidence": entry.confidence,
            }
            if scope not in {"all", resource.kind.value} or not all(
                predicate.matches(attributes) for predicate in predicates
            ):
                continue
            if (
                ref == query_ref
                or (isinstance(source, RefsSource) and ref not in seeds)
                or (not isinstance(source, RefsSource) and (ref, "") in excluded)
            ):
                continue
            text = self._store.read(resource).text
            scanned += 1
            if isinstance(source, RefsSource):
                for selected_ref, fragment in seeds[ref]:
                    first, last = fragment_range(text, fragment)
                    selected_text = "".join(
                        text.splitlines(keepends=True)[first - 1 : last]
                    )
                    candidates.append(
                        SearchCandidate(
                            selected_ref,
                            entry.display,
                            content_units(ref, selected_text, first_line=first),
                            attributes,
                        )
                    )
                continue
            units = content_units(ref, text)
            evidence: list[SearchEvidence] = []
            if anchor is not None:
                for target, relation, _, _ in self._navigation_refs(entry):
                    try:
                        actual = references.resolve(target, source_day=entry.updated_on)
                    except ReferenceError:
                        continue
                    if actual.matches(anchor):
                        position = text.find(target)
                        evidence.extend(
                            range_evidence(
                                units,
                                max(0, position),
                                position + len(target) if position >= 0 else len(text),
                                kind=EvidenceKind.REFERENCE,
                                relation=relation,
                            )
                        )
                if not evidence:
                    continue
            candidates.append(
                SearchCandidate(
                    ref,
                    entry.display,
                    units,
                    attributes,
                    tuple(dict.fromkeys(evidence)),
                )
            )
        if isinstance(source, RefsSource):
            candidates.sort(key=lambda item: seed_order[item.ref])
        return SearchCorpus(tuple(candidates), query, scanned)

    def _navigation_refs(
        self, entry: MemoryCatalogEntry
    ) -> tuple[tuple[str, str, str, str], ...]:
        from .retrieval.query import _structured_refs

        result = [
            (
                str(target),
                "memory_reference",
                self._catalog.snapshot.entries[target].display
                if target in self._catalog.snapshot.entries
                else target.kind.value,
                f"{entry.ref} references {target}",
            )
            for target in _structured_refs(self._store.read(entry.ref).document)
        ]
        lines = entry.content.splitlines()
        for reference in markdown_references(entry.content):
            try:
                target = relative_reference(
                    reference.target,
                    source_path=entry.ref.relative_path,
                    prefix="memory:",
                )
                resource, marker, fragment = target.partition("#")
                if resource.startswith("memory:") and resource.endswith(".md"):
                    target = str(
                        MemoryRef.from_relative(resource.removeprefix("memory:"))
                    ) + ("#" + fragment if marker else "")
            except (ReferenceError, MemoryContractError):
                continue
            result.append(
                (
                    target,
                    "markdown_reference",
                    reference.label or target.partition("#")[0].rsplit("/", 1)[-1],
                    lines[reference.line - 1]
                    if reference.line <= len(lines)
                    else reference.label,
                )
            )
        return tuple(dict.fromkeys(result))

    def read_daily(self, day: date | CalendarDay) -> DailyMemoryDocument | None:
        ref = MemoryRef.daily(_date(day))
        if not self._store.exists(ref):
            return None
        document = self._store.read(ref).document
        if not isinstance(document, DailyMemoryDocument):
            raise MemoryInvariantError("Daily Memory path contains another kind")
        return document

    def latest_daily_before(
        self, day: date | CalendarDay
    ) -> StoredMemoryDocument | None:
        target = _date(day)
        refs = [
            ref
            for ref in self._store.refs()
            if ref.kind is MemoryKind.DAILY and ref.day < target
        ]
        if not refs:
            return None
        return self._store.read(max(refs, key=lambda item: item.day))

    def read_document(self, ref: MemoryRef) -> StoredMemoryDocument:
        return self._store.read(ref)

    def render_document(self, document: PersistentMemoryDocument) -> str:
        return self._codec.render(document)

    def write_document(
        self,
        document: PersistentMemoryDocument,
    ) -> StoredMemoryDocument:
        """Validate the new graph before atomically replacing exactly one document."""
        with self._lock:
            # Existing storage damage is a boundary failure; a proposed invalid
            # relation/redirect is a correctable write request.
            self._catalog.rebuild()
            try:
                candidate = self._catalog.snapshot_for((document,))
            except MemoryInvariantError as exc:
                raise MemoryContractError(
                    "Memory write has invalid references or redirects"
                ) from exc
            result = self._store.write(document)
            self._catalog.install(candidate)
            return result

    def write_markdown(self, ref: MemoryRef, markdown: str) -> StoredMemoryDocument:
        try:
            document = self._codec.parse(ref, markdown)
        except MemoryInvariantError as exc:
            raise MemoryContractError(
                "Memory Markdown does not satisfy its document schema"
            ) from exc
        return self.write_document(document)

    def new_ref(self, kind: MemoryKind) -> MemoryRef:
        if kind not in {MemoryKind.FACT, MemoryKind.NOTE}:
            raise MemoryContractError("Only fact/note Links use owner-generated cites")
        prefix = "f-" if kind is MemoryKind.FACT else "n-"
        while True:
            ref = MemoryRef(kind, prefix + secrets.token_hex(8))
            if not self._store.exists(ref):
                return ref

    def rebuild_catalog(self) -> None:
        with self._lock:
            self._catalog.rebuild()

    def _require_active(self) -> ActiveMemoryStore:
        if self._active is None:
            raise MemoryInvariantError("Active Memory is not bound to a Session root")
        return self._active


def _date(value: date | CalendarDay) -> date:
    if isinstance(value, CalendarDay):
        return value.value
    if isinstance(value, date):
        return value
    raise MemoryContractError("Memory day must be a date or CalendarDay")


def _metadata_date(document: object, name: str) -> str:
    value = getattr(document, name)
    return value.isoformat()
