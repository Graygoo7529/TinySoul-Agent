"""Memory module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tinysoul.loop.day import BusinessDay
from tinysoul.runtime import ObservationEmitter, RunScope
from tinysoul.session import SessionMemoryFactsProjection

from .config import MemorySettings
from .errors import MemoryContractError
from .links import MemoryLink
from .maintenance import (
    HomeTopLinkCatalog,
    MemoryConsolidator,
    MemoryMaintenanceOutcome,
    MemoryMaintenanceService,
)
from .search import MemorySearchReranker, MemorySearchResult, MemorySearchService
from .store import MemoryDocument, MemoryStore


@dataclass(frozen=True)
class MemoryRecallResult:
    link: str
    day: str
    text: str
    digest: str


class MemoryEngine:
    """Single facade for Memory reads, search, and Maintenance."""

    def __init__(
        self,
        *,
        settings: MemorySettings,
        home_catalog: HomeTopLinkCatalog,
        observations: ObservationEmitter | None = None,
    ) -> None:
        if not isinstance(settings, MemorySettings):
            raise MemoryContractError("Memory settings are invalid")
        self._store = MemoryStore(
            root=settings.root,
            max_document_chars=settings.max_document_chars,
        )
        self._search = MemorySearchService(store=self._store, settings=settings.search)
        self._maintenance = MemoryMaintenanceService(
            store=self._store,
            home_catalog=home_catalog,
            settings=settings.maintenance,
            observations=observations,
        )

    @property
    def root(self) -> Path:
        return self._store.root

    def links(self) -> tuple[MemoryLink, ...]:
        return self._store.links()

    def exists(self, day: BusinessDay) -> bool:
        return self._maintenance.memory_exists(day)

    def read_day(self, day: BusinessDay) -> MemoryDocument | None:
        if not isinstance(day, BusinessDay):
            raise MemoryContractError("Memory read_day requires a BusinessDay")
        link = MemoryLink(day.value)
        if not self._store.exists(link):
            return None
        return self._store.read(link)

    def recall(self, memory_link: MemoryLink | str) -> MemoryRecallResult:
        link = MemoryLink.parse(memory_link) if isinstance(memory_link, str) else memory_link
        if not isinstance(link, MemoryLink):
            raise MemoryContractError("Memory recall requires a MemoryLink")
        document = self._store.read(link)
        return MemoryRecallResult(
            link=str(link),
            day=link.day.isoformat(),
            text=document.text,
            digest=document.digest,
        )

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        reranker: MemorySearchReranker | None = None,
        scope: RunScope | None = None,
    ) -> MemorySearchResult:
        return self._search.search(
            query,
            top_k=top_k,
            reranker=reranker,
            scope=scope,
        )

    def maintenance_eligible(
        self,
        projection: SessionMemoryFactsProjection | None,
    ) -> bool:
        return self._maintenance.eligible(projection)

    def run_maintenance(
        self,
        *,
        projection: SessionMemoryFactsProjection | None,
        consolidator: MemoryConsolidator | None,
        timezone: str,
        target_day: BusinessDay | None = None,
        rewrite_existing: bool = True,
        scope: RunScope | None = None,
    ) -> MemoryMaintenanceOutcome:
        return self._maintenance.run(
            projection=projection,
            consolidator=consolidator,
            timezone=timezone,
            target_day=target_day,
            rewrite_existing=rewrite_existing,
            scope=scope,
        )
