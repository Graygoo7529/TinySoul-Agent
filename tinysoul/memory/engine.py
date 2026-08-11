"""Memory owner facade for active memory and persistent five-kind documents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from collections.abc import Sequence
from pathlib import Path
import secrets

from tinysoul.infra.time import BusinessDay
from tinysoul.infra import EmbeddingClient, EmbeddingError
from tinysoul.infra.json import JsonObject, to_json_object

from .active import (
    ActiveMemoryDocument,
    ActiveMemorySnapshot,
    ActiveMemoryStore,
    MemoryPatchOperation,
)
from .catalog import (
    MemoryCatalog,
    MemoryCatalogSnapshot,
    MemoryInspectRequest,
    MemoryInspectResult,
    MemorySemanticSearch,
    resolve_redirect,
)
from .config import MemorySettings
from .documents import (
    DailyMemoryDocument,
    MemoryDocumentCodec,
    PersistentMemoryDocument,
    StoredMemoryDocument,
)
from .errors import MemoryContractError, MemoryError, MemoryInvariantError
from .embeddings import MemoryEmbeddingIndex
from .links import MemoryKind, MemoryLink
from .store import MemoryStore
from .transaction import (
    MemoryChangeSet,
    MemoryCommitOutcome,
    MemoryDocumentChange,
    MemoryTransactionService,
)


@dataclass(frozen=True)
class MemoryRecallResult:
    link: str
    kind: str
    cite: str
    content: str
    digest: str
    metadata: JsonObject
    resolution_chain: tuple[str, ...] = ()

class MemoryEngine:
    """Single assembly facade for Memory reads, writes, retrieval, and lifecycle."""

    def __init__(
        self,
        *,
        settings: MemorySettings,
        active_session_root: Path | None = None,
        semantic_search: MemorySemanticSearch | None = None,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        if not isinstance(settings, MemorySettings):
            raise MemoryContractError("Memory settings are invalid")
        self._settings = settings
        self._codec = MemoryDocumentCodec()
        self._store = MemoryStore(root=settings.root, settings=settings.documents, codec=self._codec)
        self._embeddings = (
            MemoryEmbeddingIndex(
                path=self._store.internal_root / "embedding-cache.json",
                client=embedding_client,
                cache_max_chars=settings.semantic_search.embedding_cache_max_chars,
            )
            if embedding_client is not None
            else None
        )
        if semantic_search is not None and self._embeddings is not None:
            raise MemoryContractError("Memory semantic search has multiple providers")
        self._catalog = MemoryCatalog(
            store=self._store,
            settings=settings.inspect,
            redirect_max_hops=settings.documents.redirect_max_hops,
            semantic=semantic_search or self._embeddings,
        )
        self._active = (
            ActiveMemoryStore(
                session_root=active_session_root,
                max_chars=settings.max_active_chars,
            )
            if active_session_root is not None
            else None
        )
        self._transactions = MemoryTransactionService(
            store=self._store,
            codec=self._codec,
            validate_documents=self._catalog.validate_overlay,
        )
        self.recover()

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

    def initialize_active_day(self, day: date | BusinessDay) -> ActiveMemorySnapshot:
        return self._require_active().initialize_day(_date(day))

    def active_day(self) -> BusinessDay:
        return BusinessDay(self._require_active().read().day)

    def read_active(self, day: date | BusinessDay | None = None) -> ActiveMemorySnapshot:
        return self._require_active().read(expected_day=_date(day) if day is not None else None)

    def validate_active_day(self, day: date | BusinessDay) -> ActiveMemorySnapshot:
        return self.read_active(day)

    def patch_active(
        self,
        *,
        day: date | BusinessDay,
        expected_digest: str,
        operations: tuple[MemoryPatchOperation, ...],
    ) -> ActiveMemorySnapshot:
        return self._require_active().patch(
            day=_date(day),
            expected_digest=expected_digest,
            operations=operations,
        )

    def read_archived_active(self, day: date | BusinessDay, session_archive_root: Path) -> ActiveMemorySnapshot:
        return ActiveMemoryStore(
            session_root=session_archive_root,
            max_chars=self._settings.max_active_chars,
        ).read(expected_day=_date(day))

    def archived_active_available(
        self,
        day: date | BusinessDay,
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

    def validate_archived_active(self, day: date | BusinessDay, session_archive_root: Path) -> ActiveMemorySnapshot:
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

    def inspect(
        self,
        request: MemoryInspectRequest,
        *,
        documents: Sequence[PersistentMemoryDocument] = (),
        page_overhead: int = 0,
    ) -> MemoryInspectResult:
        snapshot = self._catalog.snapshot_for(documents) if documents else None
        return self._catalog.inspect(
            request,
            snapshot=snapshot,
            page_overhead=page_overhead,
        )

    def recall(
        self,
        memory_link: MemoryLink | str,
        *,
        documents: Sequence[PersistentMemoryDocument] = (),
    ) -> MemoryRecallResult:
        link = MemoryLink.parse(memory_link) if isinstance(memory_link, str) else memory_link
        if not isinstance(link, MemoryLink):
            raise MemoryContractError("Memory recall requires a persistent MemoryLink")
        staged = {document.link: document for document in documents}
        if len(staged) != len(tuple(documents)):
            raise MemoryContractError("Memory recall draft Links are not unique")
        stored = (
            self._codec.stored(staged[link])
            if link in staged
            else self._store.read(link)
        )
        document = stored.document
        raw_metadata: dict[str, object] = {
            "schema_version": 1,
            "kind": link.kind.value,
            "cite": link.cite,
            "status": document.status.value,
            "created_on": _metadata_date(document, "created_on"),
            "updated_on": _metadata_date(document, "updated_on"),
        }
        if hasattr(document, "activity"):
            activity = getattr(document, "activity")
            raw_metadata["activity"] = {
                "last_activated_on": activity.last_activated_on.isoformat(),
                "activation_count": activity.activation_count,
            }
        for name in ("summary", "title", "relations", "evidence", "redirect_to"):
            if hasattr(document, name):
                value = getattr(document, name)
                if isinstance(value, tuple):
                    value = [str(item) for item in value]
                elif isinstance(value, MemoryLink):
                    value = str(value)
                raw_metadata[name] = value
        snapshot = self._catalog.snapshot_for(documents) if documents else self._catalog.snapshot
        chain = resolve_redirect(
            snapshot,
            link,
            max_hops=self._settings.documents.redirect_max_hops,
        )
        return MemoryRecallResult(
            link=str(link),
            kind=link.kind.value,
            cite=link.cite,
            content=stored.text,
            digest=stored.digest,
            metadata=to_json_object(raw_metadata),
            resolution_chain=tuple(str(item) for item in chain),
        )

    def read_daily(self, day: date | BusinessDay) -> DailyMemoryDocument | None:
        link = MemoryLink.daily(_date(day))
        if not self._store.exists(link):
            return None
        document = self._store.read(link).document
        if not isinstance(document, DailyMemoryDocument):
            raise MemoryInvariantError("Daily Memory path contains another kind")
        return document

    def latest_daily_before(self, day: date | BusinessDay) -> StoredMemoryDocument | None:
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
        *,
        expected_digest: str | None = None,
        expected_absent: bool = False,
    ) -> StoredMemoryDocument:
        self._catalog.validate_overlay((document,))
        result = self._store.write(
            document,
            expected_digest=expected_digest,
            expected_absent=expected_absent,
        )
        self._catalog.rebuild()
        return result

    def new_link(self, kind: MemoryKind) -> MemoryLink:
        if kind not in {MemoryKind.FACT, MemoryKind.NOTE}:
            raise MemoryContractError("Only fact/note Links use owner-generated cites")
        prefix = "f-" if kind is MemoryKind.FACT else "n-"
        while True:
            link = MemoryLink(kind, prefix + secrets.token_hex(8))
            if not self._store.exists(link):
                return link

    def prepare_changeset(
        self,
        *,
        target_day: date | BusinessDay,
        changes: tuple[MemoryDocumentChange, ...],
    ) -> MemoryChangeSet:
        self._catalog.validate_overlay(tuple(change.document for change in changes))
        return MemoryChangeSet.create(
            target_day=_date(target_day),
            base_generation=self._catalog.snapshot.generation,
            changes=changes,
        )

    def commit(self, changeset: MemoryChangeSet) -> MemoryCommitOutcome:
        outcome = self._transactions.commit(
            changeset,
            current_generation=self._catalog.snapshot.generation,
        )
        self._catalog.rebuild()
        self.refresh_embeddings(outcome.changed_links)
        return outcome

    def recover(self) -> None:
        self._transactions.recover()
        self._catalog.rebuild()

    def refresh_embeddings(self, changed_links: tuple[MemoryLink, ...] = (), scope: object | None = None) -> None:
        del changed_links, scope
        if self._embeddings is None:
            return
        documents = {
            link: (
                entry.digest,
                _embedding_text(link, entry.display, entry.content),
            )
            for link, entry in self._catalog.snapshot.entries.items()
            if entry.status == "active"
        }
        try:
            self._embeddings.refresh(documents)
        except (EmbeddingError, MemoryError):
            return

    def _require_active(self) -> ActiveMemoryStore:
        if self._active is None:
            raise MemoryInvariantError("Active Memory is not bound to a Session root")
        return self._active


def _date(value: date | BusinessDay) -> date:
    if isinstance(value, BusinessDay):
        return value.value
    if isinstance(value, date):
        return value
    raise MemoryContractError("Memory day must be a date or BusinessDay")


def _metadata_date(document: object, name: str) -> str:
    value = getattr(document, name)
    return value.isoformat()


def _embedding_text(link: MemoryLink, display: str, content: str) -> str:
    prefix = f"{link}\n{display}\n"
    remaining = max(0, 3_000 - len(prefix))
    if len(content) <= remaining:
        return prefix + content
    head = remaining // 2
    tail = remaining - head
    return f"{prefix}{content[:head]}\n...\n{content[-tail:]}"
