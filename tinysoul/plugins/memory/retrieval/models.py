"""Derived in-memory Memory catalog, references, backlinks, and retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date


from ..errors import MemoryContractError
from ..links import MemoryKind, MemoryLink


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
