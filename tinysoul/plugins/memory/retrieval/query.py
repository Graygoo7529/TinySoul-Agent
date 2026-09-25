"""Derived in-memory Memory catalog, references, backlinks, and retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256


from ..documents import PersistentMemoryDocument, StoredMemoryDocument
from ..errors import MemoryContractError, MemoryInvariantError
from ..links import MemoryLink


from .models import MemoryCatalogSnapshot


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


def _unique(values: Sequence[MemoryLink]) -> tuple[MemoryLink, ...]:
    result: list[MemoryLink] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)


def _generation(stored: Sequence[StoredMemoryDocument]) -> str:
    material = "\n".join(f"{item.link}:{item.digest}" for item in stored)
    return sha256(material.encode("utf-8")).hexdigest()[:24]
