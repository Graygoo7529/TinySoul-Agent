"""Derived in-memory Memory catalog, references, backlinks, and retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date


from ..errors import MemoryContractError
from ..refs import MemoryKind, MemoryRef


@dataclass(frozen=True)
class MemoryCatalogEntry:
    ref: MemoryRef
    display: str
    status: str
    digest: str
    content: str
    outgoing: tuple[MemoryRef, ...]
    backlinks: tuple[MemoryRef, ...] = ()
    redirect_to: MemoryRef | None = None
    updated_on: date = date.min
    confidence: str | None = None

    @property
    def document(self) -> str:
        return self.content


@dataclass(frozen=True)
class MemoryCatalogSnapshot:
    generation: str
    entries: Mapping[MemoryRef, MemoryCatalogEntry] = field(default_factory=dict)

    def get(self, ref: MemoryRef) -> MemoryCatalogEntry | None:
        return self.entries.get(ref)

    def require(self, ref: MemoryRef) -> MemoryCatalogEntry:
        entry = self.get(ref)
        if entry is None:
            raise MemoryContractError(f"Memory does not exist: {ref}")
        return entry
