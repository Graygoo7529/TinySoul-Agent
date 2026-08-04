"""Maintenance-owned Context assembly over actual Home."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from tinysoul.context import (
    BackgroundCatalog,
    BackgroundCatalogItem,
    ContextEngine,
    ContextEngineBuilder,
    ContextSettings,
)
from tinysoul.context.errors import ContextError
from tinysoul.home import AgentHomeEngine
from tinysoul.home.errors import AgentHomeError
from tinysoul.infra.config import ConfigError
from tinysoul.memory import MemoryBackgroundEntryProvider, MemoryEngine
from tinysoul.runtime import ObservationEmitter
from tinysoul.runtime.bridge import (
    RuntimeAgentHomeBridge,
    RuntimeContextBridge,
    RuntimeMemoryBridge,
)


@dataclass(frozen=True)
class ActualHomeBackgroundEntryProvider:
    """Expose actual Home as the Maintenance Background baseline."""

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


def build_maintenance_context(
    *,
    settings: ContextSettings,
    home: AgentHomeEngine,
    memory: MemoryEngine,
    observations: ObservationEmitter,
) -> ContextEngine:
    context_bridge = RuntimeContextBridge()
    home_bridge = RuntimeAgentHomeBridge()
    memory_bridge = RuntimeMemoryBridge()
    try:
        return (
            ContextEngineBuilder(system_text=settings.system_text)
            .with_journal(settings.journal)
            .with_observations(observations)
            .with_budget_max_image_bytes(settings.budget_max_image_bytes)
            .with_trace_heap(
                chunk_max_chars=settings.trace_chunk_max_chars,
                branch_factor=settings.trace_branch_factor,
                min_hot_entries=settings.trace_min_hot_entries,
            )
            .with_trace_inspect_max_chars(settings.trace_inspect_max_chars)
            .with_compression_trigger_ratio(settings.compression_trigger_ratio)
            .with_compression_target_ratio(settings.compression_target_ratio)
            .add_background_provider(
                ActualHomeBackgroundEntryProvider(
                    home=home,
                    runtime_bridge=home_bridge,
                )
            )
            .add_background_provider(
                MemoryBackgroundEntryProvider(
                    memory=memory,
                    runtime_bridge=memory_bridge,
                )
            )
            .build()
        )
    except ConfigError as exc:
        raise context_bridge.from_config_error(exc) from exc
    except ContextError as exc:
        raise context_bridge.startup_failure(
            message=str(exc),
            payload={"error_type": type(exc).__name__},
        ) from exc
    except AgentHomeError as exc:
        raise home_bridge.startup_failure(
            message=str(exc),
            payload={"error_type": type(exc).__name__},
        ) from exc
