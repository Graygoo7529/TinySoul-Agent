"""Agent Home integration for lazy BackgroundContext content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from tinysoul.context import BackgroundCatalog, BackgroundCatalogItem
from tinysoul.runtime.bridge import RuntimeAgentHomeBridge

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
                message=str(exc),
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
            skills = self.home.skill_metadata()
        except AgentHomeError as exc:
            raise self.runtime_bridge.from_home_error(exc) from exc
        core = "home:agent@AGENT.md"
        if core not in links:
            raise self.runtime_bridge.from_home_error(
                AgentHomeContractError("Agent Home core background is missing")
            )
        return BackgroundCatalog(
            owner="home",
            default_links=(core,),
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
