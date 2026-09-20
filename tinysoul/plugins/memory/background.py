"""Memory projections into Context-owned per-Turn Background."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from typing import Protocol

from tinysoul.kernel.context import BackgroundCatalog, BackgroundCatalogItem
from tinysoul.kernel.context.background import (
    HeapCandidate,
    HeapUpdate,
    heap_segment_registration,
)
from tinysoul.kernel.context.segments import (
    SegmentCapability,
    SegmentDescriptor,
    SegmentRegistration,
    SegmentShape,
    SegmentSlot,
)
from tinysoul.plugins.memory.runtime_bridge import RuntimeMemoryBridge

from .storage.active import ActiveMemoryDocument
from .services import MemoryReadService
from .errors import MemoryContractError, MemoryError, MemoryInvariantError
from .links import MemoryBackgroundRef
from .documents import DailyMemoryDocument, StoredMemoryDocument


class TargetMemoryBinding(Protocol):
    def memory_target(self) -> tuple[date, ActiveMemoryDocument]: ...


@dataclass(frozen=True)
class ActiveMemoryBackgroundEntryProvider:
    """Expose current active Memory and the nearest earlier daily."""

    memory: MemoryReadService
    runtime_bridge: RuntimeMemoryBridge = RuntimeMemoryBridge()

    async def catalog(self, active_day: date) -> BackgroundCatalog:
        try:
            await self.memory.read_active(active_day)
            latest = await self.memory.latest_daily_before(active_day)
        except MemoryError as exc:
            raise self.runtime_bridge.from_memory_error(exc) from exc
        links = [MemoryBackgroundRef.CURRENT.value]
        items = [
            BackgroundCatalogItem(
                link=MemoryBackgroundRef.CURRENT.value,
                title="Current memory",
                description="Explicit working memory for the current Business Day.",
            )
        ]
        if latest is not None:
            links.append(MemoryBackgroundRef.LATEST.value)
            items.append(
                BackgroundCatalogItem(
                    link=MemoryBackgroundRef.LATEST.value,
                    title="Latest daily memory",
                    description=f"Nearest earlier daily Memory: {latest.link}.",
                )
            )
        values = tuple(links)
        return BackgroundCatalog(
            owner="memory",
            default_links=values,
            loadable_links=values,
            evictable_default_links=(),
            items=tuple(items),
        )

    async def load(self, link: str, active_day: date) -> str:
        try:
            if link == MemoryBackgroundRef.CURRENT.value:
                return _active_projection(
                    MemoryBackgroundRef.CURRENT,
                    await self.memory.read_active(active_day),
                )
            if link == MemoryBackgroundRef.LATEST.value:
                latest = await self.memory.latest_daily_before(active_day)
                if latest is None:
                    raise MemoryInvariantError("Prepared latest Memory disappeared")
                return _latest_projection(latest)
            raise MemoryContractError(
                "Active Memory Background exposes current/latest only"
            )
        except MemoryError as exc:
            raise self.runtime_bridge.from_memory_error(
                exc, payload={"link": link}
            ) from exc


@dataclass(frozen=True)
class TargetMemoryBackgroundEntryProvider:
    """Expose archived target Memory and target-relative latest daily."""

    memory: MemoryReadService
    binding: TargetMemoryBinding
    runtime_bridge: RuntimeMemoryBridge = RuntimeMemoryBridge()

    async def catalog(self, active_day: date) -> BackgroundCatalog:
        del active_day
        try:
            target_day, snapshot = self.binding.memory_target()
            if snapshot.day != target_day:
                raise MemoryInvariantError("Memory target binding day mismatch")
            latest = await self.memory.latest_daily_before(target_day)
        except MemoryError as exc:
            raise self.runtime_bridge.from_memory_error(exc) from exc
        links = [MemoryBackgroundRef.TARGET.value]
        items = [
            BackgroundCatalogItem(
                link=MemoryBackgroundRef.TARGET.value,
                title="Target memory",
                description=f"Fixed target-day Memory for {target_day.isoformat()}.",
            )
        ]
        if latest is not None:
            links.append(MemoryBackgroundRef.LATEST.value)
            items.append(
                BackgroundCatalogItem(
                    link=MemoryBackgroundRef.LATEST.value,
                    title="Latest daily memory",
                    description=f"Nearest daily before target: {latest.link}.",
                )
            )
        values = tuple(links)
        return BackgroundCatalog(
            owner="memory",
            default_links=values,
            loadable_links=values,
            evictable_default_links=(),
            items=tuple(items),
        )

    async def load(self, link: str, active_day: date) -> str:
        del active_day
        try:
            target_day, snapshot = self.binding.memory_target()
            if link == MemoryBackgroundRef.TARGET.value:
                if snapshot.day != target_day:
                    raise MemoryInvariantError("Memory target binding day mismatch")
                return _active_projection(
                    MemoryBackgroundRef.TARGET,
                    snapshot,
                )
            if link == MemoryBackgroundRef.LATEST.value:
                latest = await self.memory.latest_daily_before(target_day)
                if latest is None:
                    raise MemoryInvariantError("Prepared latest Memory disappeared")
                return _latest_projection(latest)
            raise MemoryContractError(
                "Target Memory Background exposes target/latest only"
            )
        except MemoryError as exc:
            raise self.runtime_bridge.from_memory_error(
                exc, payload={"link": link}
            ) from exc


def _active_projection(
    ref: MemoryBackgroundRef,
    snapshot: ActiveMemoryDocument,
) -> str:
    metadata: dict[str, object] = {
        "ref": ref.value,
        "day": snapshot.day.isoformat(),
    }
    header = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    content = snapshot.content if snapshot.content else "(empty)"
    return f"{header}\n\n{content}"


def _latest_projection(stored: StoredMemoryDocument) -> str:
    if not isinstance(stored.document, DailyMemoryDocument):
        raise MemoryInvariantError("Latest daily projection received another kind")
    metadata = {
        "ref": MemoryBackgroundRef.LATEST.value,
        "resolved_link": str(stored.link),
        "day": stored.document.day.isoformat(),
    }
    return f"{json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))}\n\n{stored.text}"


MEMORY_SEGMENT = SegmentDescriptor(
    "memory",
    "memory",
    SegmentSlot.BACKGROUND,
    50,
    shape=SegmentShape.HEAP,
    capabilities=frozenset({SegmentCapability.SELECT, SegmentCapability.RECLAIM}),
)
MEMORY_CONTEXT_UPDATE = "context.memory.update"


def memory_segment_registration(
    memory: MemoryReadService,
    *,
    target: TargetMemoryBinding | None = None,
) -> SegmentRegistration[HeapUpdate, HeapCandidate]:
    source = (
        TargetMemoryBackgroundEntryProvider(memory=memory, binding=target)
        if target is not None
        else ActiveMemoryBackgroundEntryProvider(memory=memory)
    )
    return heap_segment_registration(
        MEMORY_SEGMENT, source, signal_name=MEMORY_CONTEXT_UPDATE
    )
