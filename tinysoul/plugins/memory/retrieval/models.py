"""Derived in-memory Memory catalog, references, backlinks, and retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from tinysoul.infra.json import JsonObject, to_json_object

from ..errors import MemoryContractError
from ..links import MemoryKind, MemoryLink


class MemorySemanticSearch(Protocol):
    async def similarities(
        self,
        query: str,
        documents: Mapping[MemoryLink, str],
    ) -> Mapping[MemoryLink, float]: ...


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
    confidence: str | None = None

    def to_json(self) -> JsonObject:
        return to_json_object(
            {
                "link": self.link,
                "kind": self.kind,
                "display": self.display,
                "status": self.status,
                "summary": self.summary,
                "score": round(self.score, 6),
                "reasons": list(self.reasons),
                "updated_on": self.updated_on,
                "confidence": self.confidence,
            }
        )


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
        return to_json_object(
            {
                "mode": self.mode,
                "items": [item.to_json() for item in self.items],
                "outgoing_count": self.outgoing_count,
                "backlink_count": self.backlink_count,
                "related_count": self.related_count,
                "candidate_count": self.candidate_count,
                "continuation": self.continuation,
            }
        )


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
