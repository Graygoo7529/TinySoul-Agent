"""Memory projection into Context-owned per-Turn Background."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from tinysoul.context import BackgroundCatalog
from tinysoul.maintenance import BusinessDay
from tinysoul.runtime.bridge import RuntimeMemoryBridge

from .engine import MemoryEngine
from .errors import MemoryError
from .links import MemoryLink


@dataclass(frozen=True)
class MemoryBackgroundEntryProvider:
    """Expose only the exact previous Business Day Memory, when present."""

    memory: MemoryEngine
    runtime_bridge: RuntimeMemoryBridge = RuntimeMemoryBridge()

    def catalog(self, business_day: date) -> BackgroundCatalog:
        link = MemoryLink(business_day - timedelta(days=1))
        try:
            exists = self.memory.exists(BusinessDay(link.day))
        except MemoryError as exc:
            raise self.runtime_bridge.from_memory_error(exc) from exc
        links = (str(link),) if exists else ()
        return BackgroundCatalog(
            owner="memory",
            default_links=links,
            loadable_links=links,
            evictable_default_links=links,
        )

    def load(self, link: str, business_day: date) -> str:
        expected = MemoryLink(business_day - timedelta(days=1))
        try:
            parsed = MemoryLink.parse(link)
            if parsed != expected:
                from .errors import MemoryContractError

                raise MemoryContractError(
                    "Memory Background only exposes the exact previous day"
                )
            document = self.memory.read_day(BusinessDay(parsed.day))
            if document is None:
                from .errors import MemoryInvariantError

                raise MemoryInvariantError(
                    f"Prepared Memory Background disappeared: {parsed}"
                )
            return document.text
        except MemoryError as exc:
            raise self.runtime_bridge.from_memory_error(
                exc,
                payload={"link": link},
            ) from exc
