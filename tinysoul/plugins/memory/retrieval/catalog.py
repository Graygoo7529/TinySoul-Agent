"""Derived in-memory Memory catalog, references, backlinks, and retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence


from ..documents import (
    MemoryConfidence,
    PersistentMemoryDocument,
    StoredMemoryDocument,
    inline_memory_refs,
)
from ..errors import MemoryContractError, MemoryInvariantError
from ..refs import MemoryKind, MemoryRef
from ..storage.persistent import MemoryStore


from .models import MemoryCatalogEntry, MemoryCatalogSnapshot
from .query import (
    _structured_refs,
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
        stored = tuple(self._store.read(ref) for ref in self._store.refs())
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
        by_ref = {ref: self._store.read(ref) for ref in self._store.refs()}
        for document in documents:
            by_ref[document.ref] = self._store.codec.stored(document)
        return self._snapshot_for_stored(tuple(by_ref.values()))

    def _snapshot_for_stored(
        self,
        stored: Sequence[StoredMemoryDocument],
    ) -> MemoryCatalogSnapshot:
        self._validate_stored(stored)
        by_ref = {item.ref: item for item in stored}
        outgoing: dict[MemoryRef, tuple[MemoryRef, ...]] = {}
        for item in stored:
            refs = list(_structured_refs(item.document))
            refs.extend(inline_memory_refs(item.document.content, source=item.ref))
            outgoing[item.ref] = _unique(refs)
        backlinks: dict[MemoryRef, list[MemoryRef]] = defaultdict(list)
        for source, targets in outgoing.items():
            for target in targets:
                backlinks[target].append(source)
        entries: dict[MemoryRef, MemoryCatalogEntry] = {}
        for item in stored:
            confidence = getattr(item.document, "confidence", None)
            entries[item.ref] = MemoryCatalogEntry(
                ref=item.ref,
                display=item.document.display,
                status=item.document.status.value,
                digest=item.digest,
                content=item.document.content,
                outgoing=outgoing[item.ref],
                backlinks=tuple(sorted(backlinks[item.ref], key=str)),
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
        by_ref = {item.ref: item for item in stored}
        for item in stored:
            refs = _unique(
                (
                    *_structured_refs(item.document),
                    *inline_memory_refs(item.document.content, source=item.ref),
                )
            )
            for target in refs:
                if target not in by_ref:
                    raise MemoryInvariantError(
                        f"Memory {item.ref} references missing {target}"
                    )
        _validate_redirects(by_ref, max_hops=self._redirect_max_hops)
        for item in stored:
            if item.document.status.value != "active":
                continue
            for relation in getattr(item.document, "relations", ()):
                chain = _redirect_chain(
                    by_ref,
                    relation,
                    max_hops=self._redirect_max_hops,
                )
                final = by_ref[chain[-1]].document
                if final.status.value != "active" or final.kind not in {
                    MemoryKind.ENTITY,
                    MemoryKind.CONCEPT,
                }:
                    raise MemoryInvariantError(
                        f"Active Memory relation does not resolve to active entity/concept: {relation}"
                    )
