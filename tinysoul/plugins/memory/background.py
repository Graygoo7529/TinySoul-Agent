"""Memory projections into Context-owned per-Turn Background."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from tinysoul.prompts.plugins import memory as prompt_text
from tinysoul.infra.references import ResourceLocator
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

from .documents import DailyMemoryDocument, StoredMemoryDocument
from .errors import MemoryContractError, MemoryError, MemoryInvariantError
from .refs import MemoryBackgroundRef
from .services import MemoryReadService
from .storage.active import ActiveMemoryDocument


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
        refs = [MemoryBackgroundRef.CURRENT.value]
        items = [
            BackgroundCatalogItem(
                ref=MemoryBackgroundRef.CURRENT.value,
                title=prompt_text.CURRENT_MEMORY,
                description=prompt_text.CURRENT_MEMORY_DESCRIPTION,
                resolved_locator=ResourceLocator(
                    ref="memory:current", day=active_day.isoformat()
                ),
            )
        ]
        if latest is not None:
            refs.append(MemoryBackgroundRef.LATEST.value)
            items.append(
                BackgroundCatalogItem(
                    ref=MemoryBackgroundRef.LATEST.value,
                    title=prompt_text.LATEST_DAILY_MEMORY,
                    description=prompt_text.latest_daily_description(
                        ref=str(latest.ref)
                    ),
                    resolved_locator=ResourceLocator(ref=str(latest.ref)),
                )
            )
        values = tuple(refs)
        return BackgroundCatalog(
            owner="memory",
            default_refs=values,
            loadable_refs=values,
            evictable_default_refs=(),
            items=tuple(items),
        )

    async def load(self, ref: str, active_day: date) -> str:
        try:
            if ref == MemoryBackgroundRef.CURRENT.value:
                return _active_projection(
                    MemoryBackgroundRef.CURRENT,
                    await self.memory.read_active(active_day),
                )
            if ref == MemoryBackgroundRef.LATEST.value:
                latest = await self.memory.latest_daily_before(active_day)
                if latest is None:
                    raise MemoryInvariantError("Prepared latest Memory disappeared")
                return _latest_projection(latest)
            raise MemoryContractError(
                "Active Memory Background exposes current/latest only"
            )
        except MemoryError as exc:
            raise self.runtime_bridge.from_memory_error(
                exc, payload={"ref": ref}
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
        refs = [MemoryBackgroundRef.TARGET.value]
        items = [
            BackgroundCatalogItem(
                ref=MemoryBackgroundRef.TARGET.value,
                title=prompt_text.TARGET_MEMORY,
                description=prompt_text.target_memory_description(
                    target_day=target_day.isoformat()
                ),
                resolved_locator=ResourceLocator(
                    ref="memory:current", day=target_day.isoformat()
                ),
            )
        ]
        if latest is not None:
            refs.append(MemoryBackgroundRef.LATEST.value)
            items.append(
                BackgroundCatalogItem(
                    ref=MemoryBackgroundRef.LATEST.value,
                    title=prompt_text.LATEST_DAILY_MEMORY,
                    description=prompt_text.prior_daily_description(
                        ref=str(latest.ref)
                    ),
                    resolved_locator=ResourceLocator(ref=str(latest.ref)),
                )
            )
        values = tuple(refs)
        return BackgroundCatalog(
            owner="memory",
            default_refs=values,
            loadable_refs=values,
            evictable_default_refs=(),
            items=tuple(items),
        )

    async def load(self, ref: str, active_day: date) -> str:
        del active_day
        try:
            target_day, snapshot = self.binding.memory_target()
            if ref == MemoryBackgroundRef.TARGET.value:
                if snapshot.day != target_day:
                    raise MemoryInvariantError("Memory target binding day mismatch")
                return _active_projection(
                    MemoryBackgroundRef.TARGET,
                    snapshot,
                )
            if ref == MemoryBackgroundRef.LATEST.value:
                latest = await self.memory.latest_daily_before(target_day)
                if latest is None:
                    raise MemoryInvariantError("Prepared latest Memory disappeared")
                return _latest_projection(latest)
            raise MemoryContractError(
                "Target Memory Background exposes target/latest only"
            )
        except MemoryError as exc:
            raise self.runtime_bridge.from_memory_error(
                exc, payload={"ref": ref}
            ) from exc


def _active_projection(
    ref: MemoryBackgroundRef,
    snapshot: ActiveMemoryDocument,
) -> str:
    return prompt_text.active_context(
        ref.value, snapshot.day.isoformat(), snapshot.content
    )


def _latest_projection(stored: StoredMemoryDocument) -> str:
    if not isinstance(stored.document, DailyMemoryDocument):
        raise MemoryInvariantError("Latest daily projection received another kind")
    return prompt_text.latest_context(
        str(stored.ref), stored.document.day.isoformat(), stored.text
    )


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
