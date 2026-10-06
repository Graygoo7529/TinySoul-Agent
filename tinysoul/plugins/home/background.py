"""Agent Home integration for lazy BackgroundContext content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

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
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge

from .services import HomeService
from .errors import (
    AgentHomeContractError,
    AgentHomeError,
    AgentHomeRuntimeCopyRequired,
)


@dataclass(frozen=True)
class HomeBackgroundContentLoader:
    """Load one Home top-level entry through Runtime recovery semantics."""

    home: HomeService
    ref: str
    runtime_bridge: RuntimeAgentHomeBridge = RuntimeAgentHomeBridge()

    async def load(self) -> str:
        try:
            return await self.home.read_top(self.ref)
        except AgentHomeRuntimeCopyRequired as exc:
            raise self.runtime_bridge.runtime_copy_required(
                ref=exc.ref,
                payload=exc.to_payload(),
            ) from exc
        except AgentHomeError as exc:
            raise self.runtime_bridge.from_home_error(
                exc,
                payload={"ref": self.ref},
            ) from exc


@dataclass(frozen=True)
class HomeBackgroundEntryProvider:
    """Expose the current effective Home top catalog to Context."""

    home: HomeService
    runtime_bridge: RuntimeAgentHomeBridge = RuntimeAgentHomeBridge()

    async def catalog(self, active_day: date) -> BackgroundCatalog:
        try:
            refs = await self.home.loadable_background_refs()
            defaults = await self.home.default_background_refs()
            skills = await self.home.skill_metadata()
        except AgentHomeError as exc:
            raise self.runtime_bridge.from_home_error(exc) from exc
        if any(ref not in refs for ref in defaults):
            raise self.runtime_bridge.from_home_error(
                AgentHomeContractError(
                    "Agent Home default background is absent from the top catalog"
                )
            )
        return BackgroundCatalog(
            owner="home",
            default_refs=defaults,
            loadable_refs=refs,
            items=tuple(
                BackgroundCatalogItem(
                    ref=str(skill.ref),
                    title=skill.title,
                    description=skill.description,
                )
                for skill in skills
            ),
        )

    async def load(self, ref: str, active_day: date) -> str:
        return await HomeBackgroundContentLoader(
            home=self.home,
            ref=ref,
            runtime_bridge=self.runtime_bridge,
        ).load()


@dataclass(frozen=True)
class ActualHomeBackgroundEntryProvider:
    """Expose actual Home as the Reflection Background baseline."""

    home: HomeService
    runtime_bridge: RuntimeAgentHomeBridge = RuntimeAgentHomeBridge()

    async def catalog(self, active_day: date) -> BackgroundCatalog:
        del active_day
        try:
            refs = await self.home.actual_top_refs()
            defaults = await self.home.actual_default_background_refs()
            skills = await self.home.actual_skill_metadata()
        except AgentHomeError as exc:
            raise self.runtime_bridge.from_home_error(exc) from exc
        return BackgroundCatalog(
            owner="home",
            default_refs=defaults,
            loadable_refs=refs,
            items=tuple(
                BackgroundCatalogItem(
                    ref=str(skill.ref),
                    title=skill.title,
                    description=skill.description,
                )
                for skill in skills
            ),
        )

    async def load(self, ref: str, active_day: date) -> str:
        del active_day
        try:
            return await self.home.read_actual_top(ref)
        except AgentHomeError as exc:
            raise self.runtime_bridge.from_home_error(
                exc,
                payload={"ref": ref},
            ) from exc


HOME_SEGMENT = SegmentDescriptor(
    "home",
    "home",
    SegmentSlot.BACKGROUND,
    40,
    shape=SegmentShape.HEAP,
    capabilities=frozenset({SegmentCapability.SELECT, SegmentCapability.RECLAIM}),
)
HOME_CONTEXT_UPDATE = "context.home.update"


def home_segment_registration(
    home: HomeService,
    *,
    actual: bool = False,
) -> SegmentRegistration[HeapUpdate, HeapCandidate]:
    source = (
        ActualHomeBackgroundEntryProvider(home)
        if actual
        else HomeBackgroundEntryProvider(home)
    )
    return heap_segment_registration(
        HOME_SEGMENT, source, signal_name=HOME_CONTEXT_UPDATE
    )
