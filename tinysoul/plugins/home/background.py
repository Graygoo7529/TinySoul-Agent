"""Agent Home integration for lazy BackgroundContext content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from tinysoul.kernel.context import BackgroundCatalog, BackgroundCatalogItem
from tinysoul.kernel.context.background import HeapCandidate, HeapUpdate, heap_segment_registration
from tinysoul.kernel.context.segments import SegmentCapability, SegmentDescriptor, SegmentRegistration, SegmentShape, SegmentSlot
from tinysoul.plugins.home.runtime_bridge import RuntimeAgentHomeBridge

from .engine import AgentHomeEngine
from .errors import (
    AgentHomeContractError,
    AgentHomeError,
    AgentHomeRuntimeCopyRequired,
)


@dataclass(frozen=True)
class HomeBackgroundContentLoader:
    """Load one Home top-level entry through Runtime recovery semantics."""

    home: AgentHomeEngine
    link: str
    runtime_bridge: RuntimeAgentHomeBridge = RuntimeAgentHomeBridge()

    def load(self) -> str:
        try:
            return self.home.read_top(self.link)
        except AgentHomeRuntimeCopyRequired as exc:
            raise self.runtime_bridge.runtime_copy_required(
                link=exc.link,
                payload=exc.to_payload(),
            ) from exc
        except AgentHomeError as exc:
            raise self.runtime_bridge.from_home_error(
                exc,
                payload={"link": self.link},
            ) from exc


@dataclass(frozen=True)
class HomeBackgroundEntryProvider:
    """Expose the current effective Home top catalog to Context."""

    home: AgentHomeEngine
    runtime_bridge: RuntimeAgentHomeBridge = RuntimeAgentHomeBridge()

    def catalog(self, business_day: date) -> BackgroundCatalog:
        try:
            links = self.home.loadable_background_links()
            defaults = self.home.default_background_links()
            skills = self.home.skill_metadata()
        except AgentHomeError as exc:
            raise self.runtime_bridge.from_home_error(exc) from exc
        if any(link not in links for link in defaults):
            raise self.runtime_bridge.from_home_error(
                AgentHomeContractError(
                    "Agent Home default background is absent from the top catalog"
                )
            )
        return BackgroundCatalog(
            owner="home",
            default_links=defaults,
            loadable_links=links,
            items=tuple(
                BackgroundCatalogItem(
                    link=str(skill.link),
                    title=skill.title,
                    description=skill.description,
                )
                for skill in skills
            ),
        )

    def load(self, link: str, business_day: date) -> str:
        return HomeBackgroundContentLoader(
            home=self.home,
            link=link,
            runtime_bridge=self.runtime_bridge,
        ).load()



@dataclass(frozen=True)
class ActualHomeBackgroundEntryProvider:
    """Expose actual Home as the Reflection Background baseline."""

    home: AgentHomeEngine
    runtime_bridge: RuntimeAgentHomeBridge = RuntimeAgentHomeBridge()

    def catalog(self, business_day: date) -> BackgroundCatalog:
        del business_day
        try:
            links = self.home.actual_top_links()
            defaults = self.home.actual_default_background_links()
            skills = self.home.actual_skill_metadata()
        except AgentHomeError as exc:
            raise self.runtime_bridge.from_home_error(exc) from exc
        return BackgroundCatalog(
            owner="home",
            default_links=defaults,
            loadable_links=links,
            items=tuple(
                BackgroundCatalogItem(
                    link=str(skill.link),
                    title=skill.title,
                    description=skill.description,
                )
                for skill in skills
            ),
        )

    def load(self, link: str, business_day: date) -> str:
        del business_day
        try:
            return self.home.read_actual_top(link)
        except AgentHomeError as exc:
            raise self.runtime_bridge.from_home_error(
                exc,
                payload={"link": link},
            ) from exc



HOME_SEGMENT = SegmentDescriptor("home", "home", SegmentSlot.BACKGROUND, 40, shape=SegmentShape.HEAP, capabilities=frozenset({SegmentCapability.SELECT, SegmentCapability.RECLAIM}))
HOME_CONTEXT_UPDATE = "context.home.update"


def home_segment_registration(
    home: AgentHomeEngine, *, actual: bool = False,
) -> SegmentRegistration[HeapUpdate, HeapCandidate]:
    source = ActualHomeBackgroundEntryProvider(home) if actual else HomeBackgroundEntryProvider(home)
    return heap_segment_registration(HOME_SEGMENT, source, signal_name=HOME_CONTEXT_UPDATE)
