"""Derived in-memory Memory catalog, references, backlinks, and retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
import math


from ..config import MemoryInspectSettings
from ..documents import (
    MemoryConfidence,
    PersistentMemoryDocument,
    StoredMemoryDocument,
    inline_memory_links,
)
from ..errors import MemoryContractError, MemoryInvariantError
from ..links import MemoryKind, MemoryLink
from ..storage.persistent import MemoryStore


from .models import (
    MemorySemanticSearch,
    MemoryCatalogEntry,
    MemoryInspectRequest,
    MemoryInspectItem,
    MemoryInspectResult,
    MemoryCatalogSnapshot,
)
from .query import (
    _structured_links,
    _validate_redirects,
    _redirect_chain,
    _lexical_score,
    _inspect_item,
    _fit_result_page,
    _confidence_rank,
    _request_identity,
    _semantic_text,
    _normalize,
    _terms,
    _match_summary,
    _truncate,
    _unique,
    _generation,
    _parse_continuation,
)


class MemoryCatalog:
    """Build and query derived retrieval structures from Markdown facts."""

    def __init__(
        self,
        *,
        store: MemoryStore,
        settings: MemoryInspectSettings,
        redirect_max_hops: int,
        semantic: MemorySemanticSearch | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._redirect_max_hops = redirect_max_hops
        self._semantic = semantic
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
            refs.extend(inline_memory_links(item.document.content))
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
                    *inline_memory_links(item.document.content),
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

    async def inspect(
        self,
        request: MemoryInspectRequest,
        *,
        snapshot: MemoryCatalogSnapshot | None = None,
        page_overhead: int = 0,
    ) -> MemoryInspectResult:
        if (
            isinstance(page_overhead, bool)
            or not isinstance(page_overhead, int)
            or page_overhead < 0
        ):
            raise MemoryContractError("Memory inspect page overhead is invalid")
        limit = request.limit or self._settings.default_top_k
        if limit > self._settings.max_top_k:
            raise MemoryContractError(
                f"Memory inspect limit exceeds {self._settings.max_top_k}"
            )
        current = snapshot or self._snapshot
        identity = _request_identity(request, limit=limit)
        offset = _parse_continuation(request.continuation, current.generation, identity)
        page_chars = self._settings.page_max_chars - page_overhead
        if page_chars <= 0:
            raise MemoryContractError(
                "Memory inspect page overhead exceeds page budget"
            )
        if request.memory_link is not None:
            return await self._inspect_link(
                request.memory_link,
                snapshot=current,
                identity=identity,
                max_chars=page_chars,
                kinds=request.kinds,
                limit=limit,
                offset=offset,
            )
        assert request.query is not None
        return await self._inspect_query(
            request.query,
            snapshot=current,
            identity=identity,
            max_chars=page_chars,
            kinds=request.kinds,
            limit=limit,
            offset=offset,
        )

    async def _inspect_query(
        self,
        query: str,
        *,
        snapshot: MemoryCatalogSnapshot,
        identity: str,
        max_chars: int,
        kinds: tuple[MemoryKind, ...],
        limit: int,
        offset: int,
    ) -> MemoryInspectResult:
        normalized_query = _normalize(query)
        terms = _terms(normalized_query)
        active = {
            link: entry
            for link, entry in snapshot.entries.items()
            if entry.status == "active" and (not kinds or link.kind in kinds)
        }
        semantic: Mapping[MemoryLink, float] = {}
        if self._semantic is not None and active:
            semantic = await self._semantic.similarities(
                query,
                {link: _semantic_text(entry) for link, entry in active.items()},
            )
        scored: list[tuple[float, MemoryCatalogEntry, tuple[str, ...]]] = []
        for entry in active.values():
            score, reasons = _lexical_score(entry, normalized_query, terms)
            semantic_score = semantic.get(entry.link)
            if semantic_score is not None and math.isfinite(semantic_score):
                score += max(0.0, min(1.0, float(semantic_score))) * 3.0
                reasons = (*reasons, "semantic")
            if score <= 0:
                continue
            scored.append((score, entry, reasons))
        scored.sort(
            key=lambda item: (
                -item[0],
                -item[1].updated_on.toordinal(),
                -_confidence_rank(item[1].confidence),
                str(item[1].link),
            )
        )
        candidates = scored[: self._settings.candidate_limit]
        selected = candidates[offset : offset + limit]
        proposed = tuple(
            _inspect_item(
                entry,
                score=score,
                reasons=reasons,
                summary=_match_summary(
                    entry.content,
                    terms,
                    self._settings.summary_max_chars,
                ),
            )
            for score, entry, reasons in selected
        )
        return _fit_result_page(
            mode="query",
            proposed=proposed,
            max_chars=max_chars,
            generation=snapshot.generation,
            identity=identity,
            offset=offset,
            candidate_count=len(candidates),
        )

    async def _inspect_link(
        self,
        link: MemoryLink,
        *,
        snapshot: MemoryCatalogSnapshot,
        identity: str,
        max_chars: int,
        kinds: tuple[MemoryKind, ...],
        limit: int,
        offset: int,
    ) -> MemoryInspectResult:
        entry = snapshot.require(link)
        outgoing = tuple(
            candidate
            for candidate in entry.outgoing
            if not kinds or candidate.kind in kinds
        )
        backlinks = tuple(
            candidate
            for candidate in entry.backlinks
            if not kinds or candidate.kind in kinds
        )
        neighborhood = _unique((*entry.outgoing, *entry.backlinks))
        entry_terms = _terms(_normalize(f"{entry.display} {entry.content}"))
        related_entries = {
            candidate: other
            for candidate, other in snapshot.entries.items()
            if candidate != link
            and candidate not in neighborhood
            and other.status == "active"
            and (not kinds or candidate.kind in kinds)
        }
        semantic: Mapping[MemoryLink, float] = {}
        if self._semantic is not None and related_entries:
            semantic = await self._semantic.similarities(
                _semantic_text(entry),
                {
                    candidate: _semantic_text(other)
                    for candidate, other in related_entries.items()
                },
            )
        related_scored: list[tuple[float, int, MemoryCatalogEntry, tuple[str, ...]]] = (
            []
        )
        term_count = max(1, len(entry_terms))
        for candidate, other in related_entries.items():
            overlap = len(
                entry_terms & _terms(_normalize(f"{other.display} {other.content}"))
            )
            raw_semantic_score = semantic.get(candidate)
            semantic_score = 0.0
            if raw_semantic_score is not None and math.isfinite(raw_semantic_score):
                semantic_score = max(0.0, min(1.0, float(raw_semantic_score)))
            if semantic_score <= 0 and overlap <= 0:
                continue
            reasons: list[str] = []
            if semantic_score > 0:
                reasons.append("semantic_related")
            if overlap > 0:
                reasons.append("lexical_related")
            related_scored.append((semantic_score, overlap, other, tuple(reasons)))
        related_scored.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2].updated_on.toordinal(),
                -_confidence_rank(item[2].confidence),
                str(item[2].link),
            )
        )
        related_scored = related_scored[: self._settings.candidate_limit]
        related = tuple(item[2].link for item in related_scored)
        related_details = {
            item[2].link: (
                item[0] if item[0] > 0 else min(1.0, item[1] / term_count),
                item[3],
            )
            for item in related_scored
        }
        combined = _unique((*outgoing, *backlinks, *related))
        selected = combined[offset : offset + limit]
        proposed_items: list[MemoryInspectItem] = []
        for candidate in selected:
            candidate_entry = snapshot.require(candidate)
            reasons: list[str] = []
            if candidate in outgoing:
                reasons.append("outgoing")
            if candidate in backlinks:
                reasons.append("backlink")
            if not reasons:
                related_score, related_reasons = related_details[candidate]
                reasons.extend(related_reasons)
                score = related_score
            else:
                score = 1.0
            proposed_items.append(
                _inspect_item(
                    candidate_entry,
                    score=score,
                    reasons=tuple(reasons),
                    summary=_truncate(
                        candidate_entry.content,
                        self._settings.summary_max_chars,
                    ),
                )
            )
        proposed = tuple(proposed_items)
        return _fit_result_page(
            mode="link",
            proposed=proposed,
            max_chars=max_chars,
            generation=snapshot.generation,
            identity=identity,
            offset=offset,
            candidate_count=len(combined),
            outgoing_count=len(outgoing),
            backlink_count=len(backlinks),
            related_count=len(related),
        )
