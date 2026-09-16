"""User Turn Context assembly."""

from __future__ import annotations

from tinysoul.context import ContextEngine, ContextEngineBuilder, ContextSettings
from tinysoul.context.errors import ContextError
from tinysoul.home import AgentHomeEngine
from tinysoul.home.background import home_segment_registration
from tinysoul.home.errors import AgentHomeError
from tinysoul.infra.config import ConfigError
from tinysoul.memory import MemoryEngine
from tinysoul.memory.background import memory_segment_registration
from tinysoul.runtime import ObservationEmitter
from tinysoul.home.runtime_bridge import RuntimeAgentHomeBridge
from tinysoul.context.runtime_bridge import RuntimeContextBridge


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
            .with_segment(home_segment_registration(home))
            .with_segment(memory_segment_registration(memory))
            .build()
        )
    except ConfigError as exc:
        raise context_bridge.from_config_error(exc) from exc
    except ContextError as exc:
        raise context_bridge.startup_failure(
            message="User Turn context could not be initialized.",
            payload={"error_type": type(exc).__name__},
        ) from exc
    except AgentHomeError as exc:
        raise home_bridge.startup_failure(
            message="Home context guidance could not be loaded.",
            payload={"error_type": type(exc).__name__},
        ) from exc
