"""Derived in-memory Memory catalog, references, backlinks, and retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
import math
import re
from typing import Protocol

from tinysoul.infra.json import JsonObject, to_json_object

from .config import MemoryInspectSettings
from .documents import (
    MemoryActivity,
    MemoryConfidence,
    PersistentMemoryDocument,
    StoredMemoryDocument,
    inline_memory_links,
)
from .errors import MemoryContractError, MemoryInvariantError
from .links import MemoryKind, MemoryLink
from .store import MemoryStore


class MemorySemanticSearch(Protocol):
    def similarities(
        self,
        query: str,
        documents: Mapping[MemoryLink, str],
    ) -> Mapping[MemoryLink, float]:
        ...


@dataclass(frozen=True)
class MemoryCatalogEntry:
    link: MemoryLink
    display: str
    status: str
    digest: str
    content: str
    outgoing: tuple[MemoryLink, ...]
    backlinks: tuple[MemoryLink, ...] = ()
    redirect_to: MemoryLink | None = None
    updated_on: date = date.min
    last_activated_on: date = date.min
    activation_count: int = 0
    confidence: str | None = None

    @property
    def document(self) -> str:
        return self.content


@dataclass(frozen=True)
class MemoryInspectRequest:
    query: str | None = None
    memory_link: MemoryLink | None = None
    kinds: tuple[MemoryKind, ...] = ()
    limit: int | None = None
    continuation: str | None = None

    def __post_init__(self) -> None:
        has_query = isinstance(self.query, str) and bool(self.query.strip())
        has_link = isinstance(self.memory_link, MemoryLink)
        if has_query == has_link:
            raise MemoryContractError(
                "Memory inspect requires exactly one of query or memory_link"
            )
        if self.query is not None and not has_query:
            raise MemoryContractError("Memory inspect query must be non-empty")
        kinds = tuple(self.kinds)
        if any(not isinstance(item, MemoryKind) for item in kinds):
            raise MemoryContractError("Memory inspect kinds are invalid")
        if len(set(kinds)) != len(kinds):
            raise MemoryContractError("Memory inspect kinds must be unique")
        if self.limit is not None and (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or self.limit <= 0
        ):
            raise MemoryContractError("Memory inspect limit must be positive")
        if self.continuation is not None and (
            not isinstance(self.continuation, str) or not self.continuation
        ):
            raise MemoryContractError("Memory inspect continuation is invalid")
        object.__setattr__(self, "kinds", kinds)


@dataclass(frozen=True)
class MemoryInspectItem:
    link: str
    kind: str
    display: str
    status: str
    summary: str
    score: float
    reasons: tuple[str, ...]
    updated_on: str
    activity: JsonObject
    confidence: str | None = None

    def to_json(self) -> JsonObject:
        return to_json_object({
            "link": self.link,
            "kind": self.kind,
            "display": self.display,
            "status": self.status,
            "summary": self.summary,
            "score": round(self.score, 6),
            "reasons": list(self.reasons),
            "updated_on": self.updated_on,
            "activity": self.activity,
            "confidence": self.confidence,
        })


@dataclass(frozen=True)
class MemoryInspectResult:
    mode: str
    items: tuple[MemoryInspectItem, ...]
    outgoing_count: int = 0
    backlink_count: int = 0
    related_count: int = 0
    continuation: str | None = None
    candidate_count: int = 0

    def to_json(self) -> JsonObject:
        return to_json_object({
            "mode": self.mode,
            "items": [item.to_json() for item in self.items],
            "outgoing_count": self.outgoing_count,
            "backlink_count": self.backlink_count,
            "related_count": self.related_count,
            "candidate_count": self.candidate_count,
            "continuation": self.continuation,
        })


@dataclass(frozen=True)
class MemoryCatalogSnapshot:
    generation: str
    entries: Mapping[MemoryLink, MemoryCatalogEntry] = field(default_factory=dict)

    def get(self, link: MemoryLink) -> MemoryCatalogEntry | None:
        return self.entries.get(link)

    def require(self, link: MemoryLink) -> MemoryCatalogEntry:
        entry = self.get(link)
        if entry is None:
            raise MemoryContractError(f"Memory does not exist: {link}")
        return entry


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

    def snapshot_for(
        self,
        documents: Sequence[PersistentMemoryDocument],
    ) -> MemoryCatalogSnapshot:
        """Build a validated, non-persistent view with draft documents applied."""
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
            activity = getattr(item.document, "activity", None)
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
                last_activated_on=(
                    activity.last_activated_on
                    if isinstance(activity, MemoryActivity)
                    else item.document.updated_on
                ),
                activation_count=(
                    activity.activation_count
                    if isinstance(activity, MemoryActivity)
                    else 0
                ),
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
                (*_structured_links(item.document), *inline_memory_links(item.document.content))
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
                if final.status.value != "active" or final.kind not in {MemoryKind.ENTITY, MemoryKind.CONCEPT}:
                    raise MemoryInvariantError(
                        f"Active Memory relation does not resolve to active entity/concept: {relation}"
                    )

    def inspect(
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
            raise MemoryContractError("Memory inspect page overhead exceeds page budget")
        if request.memory_link is not None:
            return self._inspect_link(
                request.memory_link,
                snapshot=current,
                identity=identity,
                max_chars=page_chars,
                kinds=request.kinds,
                limit=limit,
                offset=offset,
            )
        assert request.query is not None
        return self._inspect_query(
            request.query,
            snapshot=current,
            identity=identity,
            max_chars=page_chars,
            kinds=request.kinds,
            limit=limit,
            offset=offset,
        )

    def _inspect_query(
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
            semantic = self._semantic.similarities(
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
                -item[1].last_activated_on.toordinal(),
                -item[1].updated_on.toordinal(),
                -item[1].activation_count,
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

    def _inspect_link(
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
            semantic = self._semantic.similarities(
                _semantic_text(entry),
                {candidate: _semantic_text(other) for candidate, other in related_entries.items()},
            )
        related_scored: list[
            tuple[float, int, MemoryCatalogEntry, tuple[str, ...]]
        ] = []
        term_count = max(1, len(entry_terms))
        for candidate, other in related_entries.items():
            overlap = len(entry_terms & _terms(_normalize(f"{other.display} {other.content}")))
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
                -item[2].last_activated_on.toordinal(),
                -item[2].updated_on.toordinal(),
                -item[2].activation_count,
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


def _structured_links(document: PersistentMemoryDocument) -> tuple[MemoryLink, ...]:
    values: list[MemoryLink] = []
    for name in ("relations", "evidence"):
        values.extend(getattr(document, name, ()))
    redirect = getattr(document, "redirect_to", None)
    if isinstance(redirect, MemoryLink):
        values.append(redirect)
    return _unique(values)


def _validate_redirects(
    documents: Mapping[MemoryLink, StoredMemoryDocument],
    *,
    max_hops: int,
) -> None:
    for source, stored in documents.items():
        redirect = getattr(stored.document, "redirect_to", None)
        if redirect is None:
            continue
        visited = {source}
        current = redirect
        for _ in range(max_hops):
            if current in visited:
                raise MemoryInvariantError(f"Memory redirect cycle starts at {source}")
            visited.add(current)
            target = documents.get(current)
            if target is None:
                raise MemoryInvariantError(f"Memory redirect target is missing: {current}")
            next_link = getattr(target.document, "redirect_to", None)
            if next_link is None:
                if target.document.status.value != "active":
                    raise MemoryInvariantError(
                        f"Memory redirect does not resolve to active: {source}"
                    )
                break
            current = next_link
        else:
            raise MemoryInvariantError(f"Memory redirect exceeds hop limit: {source}")


def _redirect_chain(
    documents: Mapping[MemoryLink, StoredMemoryDocument],
    link: MemoryLink,
    *,
    max_hops: int,
) -> tuple[MemoryLink, ...]:
    chain: list[MemoryLink] = []
    current = link
    for _ in range(max_hops + 1):
        stored = documents.get(current)
        if stored is None:
            raise MemoryInvariantError(f"Memory redirect target is missing: {current}")
        chain.append(current)
        redirect = getattr(stored.document, "redirect_to", None)
        if redirect is None:
            return tuple(chain)
        current = redirect
    raise MemoryInvariantError(f"Memory redirect exceeds hop limit: {link}")


def resolve_redirect(
    snapshot: MemoryCatalogSnapshot,
    link: MemoryLink,
    *,
    max_hops: int,
) -> tuple[MemoryLink, ...]:
    chain: list[MemoryLink] = []
    current = link
    for _ in range(max_hops + 1):
        entry = snapshot.require(current)
        chain.append(current)
        if entry.status == "active":
            return tuple(chain)
        if entry.redirect_to is None:
            raise MemoryInvariantError(f"Memory redirect is unresolved: {current}")
        current = entry.redirect_to
    raise MemoryInvariantError(f"Memory redirect exceeds hop limit: {link}")


def _lexical_score(
    entry: MemoryCatalogEntry,
    query: str,
    terms: set[str],
) -> tuple[float, tuple[str, ...]]:
    display = _normalize(entry.display)
    cite = _normalize(entry.link.cite)
    content = _normalize(entry.content)
    score = 0.0
    reasons: list[str] = []
    if query == cite or query == display:
        score += 12.0
        reasons.append("exact_identity")
    elif query in cite or query in display:
        score += 7.0
        reasons.append("identity")
    if query in content:
        score += 5.0
        reasons.append("grep_phrase")
    if terms:
        display_terms = _terms(f"{cite} {display}")
        content_terms = _terms(content)
        identity_overlap = len(terms & display_terms)
        content_overlap = len(terms & content_terms)
        if identity_overlap:
            score += 3.0 * identity_overlap / len(terms)
            reasons.append("lexical_identity")
        if content_overlap:
            score += 2.0 * content_overlap / len(terms)
            reasons.append("lexical_content")
    return score, tuple(reasons)


def _inspect_item(
    entry: MemoryCatalogEntry,
    *,
    score: float,
    reasons: tuple[str, ...],
    summary: str,
) -> MemoryInspectItem:
    return MemoryInspectItem(
        link=str(entry.link),
        kind=entry.link.kind.value,
        display=entry.display,
        status=entry.status,
        summary=summary,
        score=score,
        reasons=reasons,
        updated_on=entry.updated_on.isoformat(),
        activity=to_json_object({
            "last_activated_on": entry.last_activated_on.isoformat(),
            "activation_count": entry.activation_count,
        }),
        confidence=entry.confidence,
    )


def _fit_result_page(
    *,
    mode: str,
    proposed: tuple[MemoryInspectItem, ...],
    max_chars: int,
    generation: str,
    identity: str,
    offset: int,
    candidate_count: int,
    outgoing_count: int = 0,
    backlink_count: int = 0,
    related_count: int = 0,
) -> MemoryInspectResult:
    selected: list[MemoryInspectItem] = []
    for item in proposed:
        candidate = MemoryInspectResult(
            mode=mode,
            items=tuple((*selected, item)),
            outgoing_count=outgoing_count,
            backlink_count=backlink_count,
            related_count=related_count,
            continuation=(
                _continuation(generation, identity, offset + len(selected) + 1)
                if offset + len(selected) + 1 < candidate_count
                else None
            ),
            candidate_count=candidate_count,
        )
        size = len(json.dumps(candidate.to_json(), ensure_ascii=False, separators=(",", ":")))
        if selected and size > max_chars:
            break
        if not selected and size > max_chars:
            raise MemoryInvariantError(
                "Memory inspect result cannot fit its configured page"
            )
        selected.append(item)
    next_offset = offset + len(selected)
    return MemoryInspectResult(
        mode=mode,
        items=tuple(selected),
        outgoing_count=outgoing_count,
        backlink_count=backlink_count,
        related_count=related_count,
        continuation=(
            _continuation(generation, identity, next_offset)
            if next_offset < candidate_count
            else None
        ),
        candidate_count=candidate_count,
    )


def _confidence_rank(value: str | None) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(value or "", 0)


def _request_identity(request: MemoryInspectRequest, *, limit: int) -> str:
    payload = {
        "mode": "link" if request.memory_link is not None else "query",
        "query": _normalize(request.query) if request.query is not None else None,
        "memory_link": str(request.memory_link) if request.memory_link is not None else None,
        "kinds": sorted(item.value for item in request.kinds),
        "limit": limit,
    }
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(material.encode("utf-8")).hexdigest()[:24]


def _semantic_text(entry: MemoryCatalogEntry) -> str:
    return f"{entry.link}\n{entry.display}\n{entry.content}"


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _terms(value: str) -> set[str]:
    # Latin/digits use word units while CJK runs contribute overlapping bigrams.
    units = set(re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", value))
    for run in re.findall(r"[\u3400-\u9fff]+", value):
        units.add(run)
        units.update(run[index : index + 2] for index in range(max(0, len(run) - 1)))
    return {item for item in units if item}


def _match_summary(content: str, terms: set[str], limit: int) -> str:
    normalized = content.casefold()
    positions = [normalized.find(term) for term in terms if normalized.find(term) >= 0]
    if not positions:
        return _truncate(content, limit)
    start = max(0, min(positions) - limit // 4)
    segment = content[start : start + limit]
    if start:
        segment = f"...{segment}"
    if start + limit < len(content):
        segment = f"{segment}..."
    return segment


def _truncate(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else f"{normalized[: limit - 3]}..."


def _unique(values: Sequence[MemoryLink]) -> tuple[MemoryLink, ...]:
    result: list[MemoryLink] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _generation(stored: Sequence[StoredMemoryDocument]) -> str:
    material = "\n".join(f"{item.link}:{item.digest}" for item in stored)
    return sha256(material.encode("utf-8")).hexdigest()[:24]


def _continuation(generation: str, identity: str, offset: int) -> str:
    return f"{generation}:{identity}:{offset}"


def _parse_continuation(value: str | None, generation: str, identity: str) -> int:
    if value is None:
        return 0
    parts = value.split(":")
    if len(parts) != 3:
        raise MemoryContractError("Memory inspect continuation is stale")
    prefix, request_identity, raw_offset = parts
    if prefix != generation or request_identity != identity:
        raise MemoryContractError("Memory inspect continuation is stale")
    try:
        offset = int(raw_offset)
    except ValueError as exc:
        raise MemoryContractError("Memory inspect continuation is invalid") from exc
    if offset < 0:
        raise MemoryContractError("Memory inspect continuation is invalid")
    return offset
