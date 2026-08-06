"""Derived in-memory Memory catalog, references, backlinks, and retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
import re
from typing import Protocol

from tinysoul.infra.json import JsonObject, to_json_object

from .config import MemoryInspectSettings
from .documents import (
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

    def to_json(self) -> JsonObject:
        return to_json_object({
            "link": self.link,
            "kind": self.kind,
            "display": self.display,
            "status": self.status,
            "summary": self.summary,
            "score": round(self.score, 6),
            "reasons": list(self.reasons),
        })


@dataclass(frozen=True)
class MemoryInspectResult:
    mode: str
    items: tuple[MemoryInspectItem, ...]
    outgoing: tuple[str, ...] = ()
    backlinks: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    continuation: str | None = None
    candidate_count: int = 0


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
            entries[item.link] = MemoryCatalogEntry(
                link=item.link,
                display=item.document.display,
                status=item.document.status.value,
                digest=item.digest,
                content=item.document.content,
                outgoing=outgoing[item.link],
                backlinks=tuple(sorted(backlinks[item.link], key=str)),
                redirect_to=getattr(item.document, "redirect_to", None),
            )
        self._snapshot = MemoryCatalogSnapshot(
            generation=_generation(stored),
            entries=entries,
        )
        return self._snapshot

    def validate_overlay(
        self,
        documents: Sequence[PersistentMemoryDocument],
    ) -> None:
        by_link = {link: self._store.read(link) for link in self._store.links()}
        for document in documents:
            by_link[document.link] = self._store.codec.stored(document)
        self._validate_stored(tuple(by_link.values()))

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
            if item.document.status.value != "active" or item.link.kind is not MemoryKind.NOTE:
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
                        f"Active Note relation does not resolve to active entity/concept: {relation}"
                    )

    def inspect(self, request: MemoryInspectRequest) -> MemoryInspectResult:
        limit = request.limit or self._settings.default_top_k
        if limit > self._settings.max_top_k:
            raise MemoryContractError(
                f"Memory inspect limit exceeds {self._settings.max_top_k}"
            )
        offset = _parse_continuation(request.continuation, self._snapshot.generation)
        if request.memory_link is not None:
            return self._inspect_link(request.memory_link, limit=limit, offset=offset)
        assert request.query is not None
        return self._inspect_query(
            request.query,
            kinds=request.kinds,
            limit=limit,
            offset=offset,
        )

    def _inspect_query(
        self,
        query: str,
        *,
        kinds: tuple[MemoryKind, ...],
        limit: int,
        offset: int,
    ) -> MemoryInspectResult:
        normalized_query = _normalize(query)
        terms = _terms(normalized_query)
        active = {
            link: entry
            for link, entry in self._snapshot.entries.items()
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
        scored.sort(key=lambda item: (-item[0], str(item[1].link)))
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
        items = _fit_page(proposed, self._settings.page_max_chars)
        next_offset = offset + len(items)
        return MemoryInspectResult(
            mode="query",
            items=items,
            continuation=(
                _continuation(self._snapshot.generation, next_offset)
                if next_offset < len(candidates)
                else None
            ),
            candidate_count=len(candidates),
        )

    def _inspect_link(
        self,
        link: MemoryLink,
        *,
        limit: int,
        offset: int,
    ) -> MemoryInspectResult:
        entry = self._snapshot.require(link)
        neighborhood = _unique((*entry.outgoing, *entry.backlinks))
        related_scored: list[tuple[int, MemoryLink]] = []
        entry_terms = _terms(_normalize(f"{entry.display} {entry.content}"))
        for candidate, other in self._snapshot.entries.items():
            if candidate == link or candidate in neighborhood or other.status != "active":
                continue
            overlap = len(entry_terms & _terms(_normalize(f"{other.display} {other.content}")))
            if overlap:
                related_scored.append((overlap, candidate))
        related_scored.sort(key=lambda item: (-item[0], str(item[1])))
        related = tuple(link for _, link in related_scored)
        combined = _unique((*entry.outgoing, *entry.backlinks, *related))
        selected = combined[offset : offset + limit]
        proposed = tuple(
            _inspect_item(
                self._snapshot.require(candidate),
                score=1.0,
                reasons=(
                    "outgoing"
                    if candidate in entry.outgoing
                    else "backlink"
                    if candidate in entry.backlinks
                    else "lexical_related",
                ),
                summary=_truncate(
                    self._snapshot.require(candidate).content,
                    self._settings.summary_max_chars,
                ),
            )
            for candidate in selected
        )
        items = _fit_page(proposed, self._settings.page_max_chars)
        next_offset = offset + len(items)
        return MemoryInspectResult(
            mode="link",
            items=items,
            outgoing=tuple(str(item) for item in entry.outgoing),
            backlinks=tuple(str(item) for item in entry.backlinks),
            related=tuple(str(item) for item in related[:limit]),
            continuation=(
                _continuation(self._snapshot.generation, next_offset)
                if next_offset < len(combined)
                else None
            ),
            candidate_count=len(combined),
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
    )


def _fit_page(
    items: tuple[MemoryInspectItem, ...],
    max_chars: int,
) -> tuple[MemoryInspectItem, ...]:
    selected: list[MemoryInspectItem] = []
    used = 2
    for item in items:
        size = len(
            json.dumps(
                item.to_json(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        ) + 1
        if selected and used + size > max_chars:
            break
        if not selected and used + size > max_chars:
            raise MemoryInvariantError(
                "Memory inspect result cannot fit its configured page"
            )
        selected.append(item)
        used += size
    return tuple(selected)


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


def _continuation(generation: str, offset: int) -> str:
    return f"{generation}:{offset}"


def _parse_continuation(value: str | None, generation: str) -> int:
    if value is None:
        return 0
    prefix, separator, raw_offset = value.partition(":")
    if not separator or prefix != generation:
        raise MemoryContractError("Memory inspect continuation is stale")
    try:
        offset = int(raw_offset)
    except ValueError as exc:
        raise MemoryContractError("Memory inspect continuation is invalid") from exc
    if offset < 0:
        raise MemoryContractError("Memory inspect continuation is invalid")
    return offset
