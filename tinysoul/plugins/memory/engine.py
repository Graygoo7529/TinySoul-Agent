"""Memory owner facade for active memory and persistent five-kind documents."""

from __future__ import annotations

import secrets
from datetime import date
from pathlib import Path
from threading import RLock

from tinysoul.infra.json import JsonObject
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
    content_units,
    fragment_range,
    inspect_document,
    range_evidence,
)
from tinysoul.kernel.retrieval.engine import VectorSource
from tinysoul.kernel.retrieval.operations import SearchCorpus

from .config import MemorySettings
from .documents import (
    DailyMemoryDocument,
    MemoryDocumentCodec,
    PersistentMemoryDocument,
    StoredMemoryDocument,
)
from .errors import MemoryContractError, MemoryInvariantError
from .links import MemoryKind, MemoryLink
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

    def links(
        self,
        *,
        kinds: tuple[MemoryKind, ...] | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[MemoryLink, ...]:
        result = tuple(self._catalog.snapshot.entries)
        if kinds:
            result = tuple(link for link in result if link.kind in kinds)
        if statuses:
            result = tuple(
                link
                for link in result
                if self._catalog.snapshot.require(link).status in statuses
            )
        return tuple(sorted(result, key=str))

    def canonical_reference(
        self, resource: str, fragment: str = "", source_day: date | None = None
    ) -> ResourceTarget:
        try:
            link = MemoryLink.from_resource(resource)
            chain = resolve_redirect(
                self._catalog.snapshot,
                link,
                max_hops=self._settings.documents.redirect_max_hops,
            )
            return ResourceTarget(str(chain[-1]), fragment)
        except MemoryContractError as exc:
            raise ReferenceError(
                "Memory reference is not a readable persistent identity"
            ) from exc

    def inspect(
        self,
        memory_link: str,
        *,
        view: str = "content",
        continuation: str | None = None,
        max_chars: int | None = None,
    ) -> JsonObject:
        resource, _, fragment = memory_link.partition("#")
        link = MemoryLink.from_resource(resource)
        stored = self._store.read(link)
        chain = resolve_redirect(
            self._catalog.snapshot,
            link,
            max_hops=self._settings.documents.redirect_max_hops,
        )
        if max_chars is not None and (type(max_chars) is not int or max_chars < 512):
            raise MemoryContractError("Inspect max_chars must be at least 512")
        direct_refs = tuple(
            dict.fromkeys(
                target
                for target, _, _ in self._navigation_refs(
                    self._catalog.snapshot.require(link)
                )
            )
        )
        return inspect_document(
            owner="memory",
            ref=memory_link,
            text=stored.text,
            direct_refs=direct_refs,
            view=view,
            continuation=continuation,
            max_chars=min(
                max_chars or self._settings.inspect.page_max_chars,
                self._settings.inspect.page_max_chars,
            ),
            metadata={
                "kind": link.kind.value,
                "status": stored.document.status.value,
                "display": stored.document.display,
                "resolution_chain": [str(item) for item in chain],
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
                "Memory scope must be all or one persistent document kind",
            )
        predicates = MEMORY_SEARCH_FILTERS.parse(getattr(source, "where", {}))

        def identity(ref: str) -> tuple[str, str]:
            resource, _, fragment = ref.partition("#")
            try:
                return str(MemoryLink.from_resource(resource)), fragment
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
                if MemoryLink.parse(canonical) not in snapshot.entries:
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
                query = self._store.read(MemoryLink.parse(query_ref)).text
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
        for link, entry in entries:
            ref = str(link)
            attributes: JsonObject = {
                "kind": link.kind.value,
                "status": entry.status,
                "updated_on": entry.updated_on.isoformat(),
                "confidence": entry.confidence,
            }
            if scope not in {"all", link.kind.value} or not all(
                predicate.matches(attributes) for predicate in predicates
            ):
                continue
            if (
                ref == query_ref
                or (isinstance(source, RefsSource) and ref not in seeds)
                or (not isinstance(source, RefsSource) and (ref, "") in excluded)
            ):
                continue
            text = self._store.read(link).text
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
                for target, relation, _ in self._navigation_refs(entry):
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
    ) -> tuple[tuple[str, str, str], ...]:
        from .retrieval.query import _structured_links

        result = [
            (str(target), "memory_reference", f"{entry.link} references {target}")
            for target in _structured_links(self._store.read(entry.link).document)
        ]
        lines = entry.content.splitlines()
        for reference in markdown_references(entry.content):
            try:
                target = relative_reference(
                    reference.target,
                    source_path=entry.link.relative_path,
                    prefix="memory:",
                )
                resource, marker, fragment = target.partition("#")
                if resource.startswith("memory:") and resource.endswith(".md"):
                    target = str(
                        MemoryLink.from_relative(resource.removeprefix("memory:"))
                    ) + ("#" + fragment if marker else "")
            except (ReferenceError, MemoryContractError):
                continue
            result.append(
                (
                    target,
                    "markdown_link",
                    lines[reference.line - 1]
                    if reference.line <= len(lines)
                    else reference.label,
                )
            )
        return tuple(dict.fromkeys(result))

    def read_daily(self, day: date | CalendarDay) -> DailyMemoryDocument | None:
        link = MemoryLink.daily(_date(day))
        if not self._store.exists(link):
            return None
        document = self._store.read(link).document
        if not isinstance(document, DailyMemoryDocument):
            raise MemoryInvariantError("Daily Memory path contains another kind")
        return document

    def latest_daily_before(
        self, day: date | CalendarDay
    ) -> StoredMemoryDocument | None:
        target = _date(day)
        links = [
            link
            for link in self._store.links()
            if link.kind is MemoryKind.DAILY and link.day < target
        ]
        if not links:
            return None
        return self._store.read(max(links, key=lambda item: item.day))

    def read_document(self, link: MemoryLink) -> StoredMemoryDocument:
        return self._store.read(link)

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

    def write_markdown(self, link: MemoryLink, markdown: str) -> StoredMemoryDocument:
        try:
            document = self._codec.parse(link, markdown)
        except MemoryInvariantError as exc:
            raise MemoryContractError(
                "Memory Markdown does not satisfy its document schema"
            ) from exc
        return self.write_document(document)

    def new_link(self, kind: MemoryKind) -> MemoryLink:
        if kind not in {MemoryKind.FACT, MemoryKind.NOTE}:
            raise MemoryContractError("Only fact/note Links use owner-generated cites")
        prefix = "f-" if kind is MemoryKind.FACT else "n-"
        while True:
            link = MemoryLink(kind, prefix + secrets.token_hex(8))
            if not self._store.exists(link):
                return link

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
