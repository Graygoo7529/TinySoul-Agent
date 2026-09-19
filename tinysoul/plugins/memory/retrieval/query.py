"""Derived in-memory Memory catalog, references, backlinks, and retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import re


from ..documents import PersistentMemoryDocument, StoredMemoryDocument
from ..errors import MemoryContractError, MemoryInvariantError
from ..links import MemoryLink


from .models import (
    MemoryCatalogEntry,
    MemoryInspectRequest,
    MemoryInspectItem,
    MemoryInspectResult,
    MemoryCatalogSnapshot,
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
                raise MemoryInvariantError(
                    f"Memory redirect target is missing: {current}"
                )
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
        size = len(
            json.dumps(candidate.to_json(), ensure_ascii=False, separators=(",", ":"))
        )
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
        "memory_link": (
            str(request.memory_link) if request.memory_link is not None else None
        ),
        "kinds": sorted(item.value for item in request.kinds),
        "limit": limit,
    }
    material = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
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
