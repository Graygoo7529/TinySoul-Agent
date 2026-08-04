"""User Turn Context assembly."""

from __future__ import annotations

from tinysoul.context import ContextEngine, ContextEngineBuilder, ContextSettings
from tinysoul.context.errors import ContextError
from tinysoul.home import AgentHomeEngine, HomeBackgroundEntryProvider
from tinysoul.home.errors import AgentHomeError
from tinysoul.infra.config import ConfigError
from tinysoul.memory import MemoryBackgroundEntryProvider, MemoryEngine
from tinysoul.runtime import ObservationEmitter
from tinysoul.runtime.bridge import (
    RuntimeAgentHomeBridge,
    RuntimeContextBridge,
    RuntimeMemoryBridge,
)


def build_user_context(
    *,
    settings: ContextSettings,
    home: AgentHomeEngine,
    memory: MemoryEngine,
    observations: ObservationEmitter,
) -> ContextEngine:
    """Build User Context from effective Home and Memory projections."""

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
                HomeBackgroundEntryProvider(
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
