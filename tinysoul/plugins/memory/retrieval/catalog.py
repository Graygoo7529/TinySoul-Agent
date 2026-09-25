"""Derived in-memory Memory catalog, references, backlinks, and retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence


from ..documents import (
    MemoryConfidence,
    PersistentMemoryDocument,
    StoredMemoryDocument,
    inline_memory_links,
)
from ..errors import MemoryContractError, MemoryInvariantError
from ..links import MemoryKind, MemoryLink
from ..storage.persistent import MemoryStore


from .models import MemoryCatalogEntry, MemoryCatalogSnapshot
from .query import (
    _structured_links,
    _validate_redirects,
    _redirect_chain,
    _unique,
    _generation,
)


class MemoryCatalog:
    """Build and query derived retrieval structures from Markdown facts."""

    def __init__(
        self,
        *,
        store: MemoryStore,
        redirect_max_hops: int,
    ) -> None:
        self._store = store
        self._redirect_max_hops = redirect_max_hops
        self._snapshot = MemoryCatalogSnapshot(generation=_generation(()))

    @property
    def snapshot(self) -> MemoryCatalogSnapshot:
        return self._snapshot

    def rebuild(self) -> MemoryCatalogSnapshot:
        stored = tuple(self._store.read(link) for link in self._store.links())
        snapshot = self._snapshot_for_stored(stored)
        self._snapshot = snapshot
        return snapshot

    def install(self, snapshot: MemoryCatalogSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot_for(
        self,
        documents: Sequence[PersistentMemoryDocument],
    ) -> MemoryCatalogSnapshot:
        """Prepare a validated index before the owner replaces a document."""
        by_link = {link: self._store.read(link) for link in self._store.links()}
        for document in documents:
            by_link[document.link] = self._store.codec.stored(document)
        return self._snapshot_for_stored(tuple(by_link.values()))

    def _snapshot_for_stored(
        self,
        stored: Sequence[StoredMemoryDocument],
    ) -> MemoryCatalogSnapshot:
        self._validate_stored(stored)
        by_link = {item.link: item for item in stored}
        outgoing: dict[MemoryLink, tuple[MemoryLink, ...]] = {}
        for item in stored:
            refs = list(_structured_links(item.document))
            refs.extend(inline_memory_links(item.document.content, source=item.link))
            outgoing[item.link] = _unique(refs)
        backlinks: dict[MemoryLink, list[MemoryLink]] = defaultdict(list)
        for source, targets in outgoing.items():
            for target in targets:
                backlinks[target].append(source)
        entries: dict[MemoryLink, MemoryCatalogEntry] = {}
        for item in stored:
            confidence = getattr(item.document, "confidence", None)
            entries[item.link] = MemoryCatalogEntry(
                link=item.link,
                display=item.document.display,
                status=item.document.status.value,
                digest=item.digest,
                content=item.document.content,
                outgoing=outgoing[item.link],
                backlinks=tuple(sorted(backlinks[item.link], key=str)),
                redirect_to=getattr(item.document, "redirect_to", None),
                updated_on=item.document.updated_on,
                confidence=(
                    confidence.value
                    if isinstance(confidence, MemoryConfidence)
                    else None
                ),
            )
        return MemoryCatalogSnapshot(
            generation=_generation(stored),
            entries=entries,
        )

    def validate_overlay(
        self,
        documents: Sequence[PersistentMemoryDocument],
    ) -> None:
        self.snapshot_for(documents)

    def _validate_stored(self, stored: Sequence[StoredMemoryDocument]) -> None:
        by_link = {item.link: item for item in stored}
        for item in stored:
            refs = _unique(
                (
                    *_structured_links(item.document),
                    *inline_memory_links(item.document.content, source=item.link),
                )
            )
            for target in refs:
                if target not in by_link:
                    raise MemoryInvariantError(
                        f"Memory {item.link} references missing {target}"
                    )
        _validate_redirects(by_link, max_hops=self._redirect_max_hops)
        for item in stored:
            if item.document.status.value != "active":
                continue
            for relation in getattr(item.document, "relations", ()):
                chain = _redirect_chain(
                    by_link,
                    relation,
                    max_hops=self._redirect_max_hops,
                )
                final = by_link[chain[-1]].document
                if final.status.value != "active" or final.kind not in {
                    MemoryKind.ENTITY,
                    MemoryKind.CONCEPT,
                }:
                    raise MemoryInvariantError(
                        f"Active Memory relation does not resolve to active entity/concept: {relation}"
                    )
