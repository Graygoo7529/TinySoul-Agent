"""Explicit Turn segment registration, rendering and prepared updates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from tinysoul.infra.concurrency import AsyncResourceScope, CleanupDiagnostic
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import (
    RunLevel,
    RuntimeException,
    RuntimeTransferInterrupt,
    Signal,
)

from ..errors import (
    ContextContractError,
    ContextError,
    ContextInvariantError,
    ContextInspectFailureReason,
    ContextInspectRequestError,
)
from ..background import BackgroundPatch
from ..providers import SegmentSelectionView


from .protocol import (
    TurnInfo,
    SegmentCapability,
    SegmentShape,
    SegmentProjection,
    SegmentReclaim,
    InspectableSegment,
    SearchableSegment,
    SelectableSegment,
    ReclaimableSegment,
)
from .registration import RegisteredSegment, _OpenedSegment, _Installation
from ..disclosure import DisclosureSearchEntry


@dataclass(frozen=True)
class SegmentRegistry:
    registrations: tuple[RegisteredSegment, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "registrations", tuple(self.registrations))
        ids = tuple(item.descriptor.id for item in self.registrations)
        routes = tuple(
            item.signal_name
            for item in self.registrations
            if item.signal_name is not None
        )
        if len(set(ids)) != len(ids) or len(set(routes)) != len(routes):
            raise ContextContractError(
                "Segment identities and update routes must be unique"
            )
        prefixes = tuple(
            prefix
            for item in self.registrations
            for prefix in item.descriptor.ref_prefixes
        )
        for index, prefix in enumerate(prefixes):
            if any(
                prefix.startswith(other) or other.startswith(prefix)
                for other in prefixes[:index]
            ):
                raise ContextContractError("Segment reference routes must not overlap")

    def register(self, registration: RegisteredSegment) -> SegmentRegistry:
        return SegmentRegistry((*self.registrations, registration))

    def for_turn(self, info: TurnInfo) -> TurnSegments:
        return TurnSegments(info, self.registrations)


@dataclass(frozen=True)
class PreparedSegmentBatch:
    """Opaque candidate owned by the Turn which prepared it; installed once."""

    installations: tuple[_Installation, ...]


class TurnSegments:
    """Own opened views and install a batch only after every prepare succeeds."""

    def __init__(
        self, info: TurnInfo, registrations: tuple[RegisteredSegment, ...]
    ) -> None:
        self._info = info
        self._registrations = registrations
        self._opened: list[_OpenedSegment] = []
        self._resources = AsyncResourceScope()
        self._opening = False
        self._ready = False
        self._closed = False
        self._install_failed = False
        self._preparing = False
        self._pending: PreparedSegmentBatch | None = None

    async def open(self) -> None:
        if self._opening or self._closed:
            raise ContextContractError("Turn segments can only be opened once")
        self._opening = True
        ordered = sorted(self._registrations, key=lambda item: item.descriptor.sort_key)
        try:
            for registration in ordered:
                opened = await registration.open(self._info)
                self._resources.register(opened.descriptor.id, opened.segment.close)
                self._opened.append(opened)
                declared = opened.descriptor.capabilities
                if SegmentCapability.SEARCH in declared and not isinstance(
                    opened.segment, SearchableSegment
                ):
                    raise ContextContractError(
                        "Search capability requires an owned raw-source projection"
                    )
                if SegmentCapability.INSPECT in declared and not isinstance(
                    opened.segment, InspectableSegment
                ):
                    raise ContextContractError(
                        "A reference route requires an inspectable segment"
                    )
                if SegmentCapability.SELECT in declared and (
                    not isinstance(opened.segment, SelectableSegment)
                    or opened.updates is None
                ):
                    raise ContextContractError(
                        "Selection capability requires a view and update channel"
                    )
                if SegmentCapability.RECLAIM in declared and not isinstance(
                    opened.segment, ReclaimableSegment
                ):
                    raise ContextContractError(
                        "Reclamation capability requires a reclaim handler"
                    )
        except (Exception, asyncio.CancelledError):
            try:
                await self.close()
            except asyncio.CancelledError:
                # close joins all owners; preserve the original open failure.
                pass
            raise
        self._ready = True

    def accepts(self, signal: Signal) -> bool:
        return any(item.signal_name == signal.name for item in self._opened)

    def selection_view(self) -> SegmentSelectionView:
        self._require_ready()
        views = tuple(
            item.segment.selection_view()
            for item in self._opened
            if SegmentCapability.SELECT in item.descriptor.capabilities
            and isinstance(item.segment, SelectableSegment)
        )
        return SegmentSelectionView(
            available=tuple(ref for view in views for ref in view.available),
            loaded=tuple(ref for view in views for ref in view.loaded),
            protected=tuple(ref for view in views for ref in view.protected),
        )

    def selection_signals(
        self, patch: BackgroundPatch, source: Signal
    ) -> tuple[Signal, ...]:
        """Route a validated generic selection to each contributing owner."""
        self._require_ready()
        signals: list[Signal] = []
        for item in self._opened:
            if (
                SegmentCapability.SELECT not in item.descriptor.capabilities
                or not isinstance(item.segment, SelectableSegment)
            ):
                continue
            refs = set(item.segment.selection_view().available)
            load = tuple(ref for ref in patch.load_links if ref in refs)
            evict = tuple(ref for ref in patch.evict_links if ref in refs)
            if not load and not evict:
                continue
            if item.signal_name is None:
                raise ContextInvariantError(
                    "Selectable segment requires an update channel"
                )
            signals.append(
                Signal(
                    name=item.signal_name,
                    source=source.source,
                    scope=source.scope,
                    payload={"load_links": list(load), "evict_links": list(evict)},
                )
            )
        return tuple(signals)

    def reclaim(self, required_chars: int) -> SegmentReclaim:
        self._require_ready()
        reclaimed = 0
        refs: list[str] = []
        for item in sorted(
            self._opened,
            key=lambda item: (
                tuple(SegmentShape).index(item.descriptor.shape),
                item.descriptor.sort_key,
            ),
        ):
            if reclaimed >= required_chars:
                break
            if SegmentCapability.RECLAIM in item.descriptor.capabilities and isinstance(
                item.segment, ReclaimableSegment
            ):
                result = item.segment.reclaim(required_chars - reclaimed)
                reclaimed += result.reclaimed_chars
                refs.extend(result.evicted_refs)
        return SegmentReclaim(reclaimed, tuple(refs))

    async def prepare(self, signals: tuple[Signal, ...]) -> PreparedSegmentBatch:
        self._require_ready()
        if self._preparing:
            raise ContextContractError("Segment preparation is already in progress")
        if any(not self.accepts(signal) for signal in signals):
            raise ContextContractError("No registered segment consumes this update")
        for signal in signals:
            turn = signal.scope.nearest(RunLevel.TURN)
            if turn is None or turn.name != self._info.turn_id:
                raise ContextContractError("Segment update belongs to another Turn")
        self._pending = None
        self._preparing = True
        prepared: list[_Installation] = []
        try:
            for opened in self._opened:
                batch = tuple(
                    signal for signal in signals if signal.name == opened.signal_name
                )
                if batch:
                    if opened.updates is None:
                        raise ContextInvariantError(
                            "Read-only segment received an update"
                        )
                    prepared.append(await opened.updates.prepare(batch))
            self._require_ready()
            self._pending = PreparedSegmentBatch(tuple(prepared))
            return self._pending
        finally:
            self._preparing = False

    def install(self, prepared: PreparedSegmentBatch) -> None:
        self._require_ready()
        if prepared is not self._pending or self._preparing:
            raise ContextContractError(
                "Prepared segment batch is stale or belongs to another Turn"
            )
        self._pending = None
        try:
            for item in prepared.installations:
                item.install()
        except (Exception, asyncio.CancelledError) as exc:
            self._install_failed = True
            raise ContextInvariantError(
                "Context segment installation failed; batch cannot be replayed"
            ) from exc

    async def search_entries(
        self, scope: str, seed_refs: tuple[str, ...] = ()
    ) -> tuple[DisclosureSearchEntry, ...]:
        self._require_ready()
        result = []
        unmatched = set(seed_refs)
        for item in self._opened:
            if SegmentCapability.SEARCH not in item.descriptor.capabilities or (
                scope != "all" and item.descriptor.id != scope
            ):
                continue
            assert isinstance(item.segment, SearchableSegment)
            seeds = tuple(
                ref
                for ref in seed_refs
                if any(
                    ref.startswith(prefix) for prefix in item.descriptor.ref_prefixes
                )
            )
            unmatched.difference_update(seeds)
            if seed_refs and not seeds:
                continue
            result.extend(await item.segment.search_entries(seeds))
        if unmatched:
            raise ContextInspectRequestError(
                ContextInspectFailureReason.UNKNOWN_REF,
                "Seed refs are outside the requested Context source scope",
            )
        return tuple(result)

    async def inspect(
        self, ref: str, *, query: str | None = None, continuation: str | None = None
    ) -> JsonObject:
        self._require_ready()
        for item in self._opened:
            if any(ref.startswith(prefix) for prefix in item.descriptor.ref_prefixes):
                assert isinstance(item.segment, InspectableSegment)
                if (
                    query is not None
                    and SegmentCapability.QUERY not in item.descriptor.capabilities
                ):
                    raise ContextInspectRequestError(
                        ContextInspectFailureReason.QUERY_UNSUPPORTED,
                        "This owner supports navigation but not query; inspect without query",
                        constraint={"ref": ref},
                    )
                try:
                    return to_json_object(
                        await item.segment.inspect(
                            ref, query=query, continuation=continuation
                        )
                    )
                except (ContextError, RuntimeException, RuntimeTransferInterrupt):
                    raise
                except Exception as exc:
                    raise ContextInvariantError(
                        "Segment inspector violated its contract"
                    ) from exc
        raise ContextInspectRequestError(
            ContextInspectFailureReason.UNKNOWN_REF,
            "No Context segment owns this reference",
            constraint={"ref": ref},
        )

    def render(self) -> tuple[SegmentProjection, ...]:
        self._require_ready()
        try:
            return tuple(
                SegmentProjection(item.descriptor, item.segment.render())
                for item in self._opened
            )
        except Exception as exc:
            raise ContextInvariantError(
                "Segment could not render its installed view"
            ) from exc

    def seal(self) -> JsonObject:
        if self._closed:
            return {}
        try:
            return {
                item.descriptor.id: to_json_object(item.segment.seal())
                for item in self._opened
            }
        except Exception as exc:
            raise ContextInvariantError(
                "Segment could not seal its installed view"
            ) from exc

    async def close(self) -> tuple[CleanupDiagnostic, ...]:
        self._closed = True
        return await self._resources.close()

    def _require_ready(self) -> None:
        if not self._ready or self._closed or self._install_failed:
            raise ContextContractError(
                "Turn segments are not available for composition or updates"
            )
