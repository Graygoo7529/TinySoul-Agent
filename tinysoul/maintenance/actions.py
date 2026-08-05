"""Maintenance-owned ActionEngine assembly."""

from __future__ import annotations

from tinysoul.action import (
    ActionEngine,
    ActionEngineBuilder,
    ActionError,
    builtin_action_catalog_root,
)
from tinysoul.context import ContextEngine
from tinysoul.context.actions import register_context_actions
from tinysoul.infra.config import ConfigError
from tinysoul.runtime import ObservationEmitter
from tinysoul.runtime.bridge import (
    RuntimeActionBridge,
    RuntimeContextBridge,
    RuntimeSessionBridge,
)
from tinysoul.session.actions import SessionInspector, register_session_actions

from .errors import MaintenanceContractError
from .home import (
    HOME_MAINTENANCE_ACTIONS,
    HomeMaintenanceActionController,
    register_home_maintenance_actions,
)
from .memory import (
    MEMORY_MAINTENANCE_ACTIONS,
    MemoryMaintenanceActionController,
    register_memory_maintenance_actions,
)
from .resources import maintenance_action_catalog_root

COMMON_MAINTENANCE_READ_ACTIONS = (
    "core.context.inspect",
    "core.session.inspect",
)


def build_maintenance_action(
    *,
    kind: str,
    context: ContextEngine,
    session: SessionInspector,
    observations: ObservationEmitter,
    home_controller: HomeMaintenanceActionController,
    memory_controller: MemoryMaintenanceActionController,
    llm_action_timeout_seconds: float = 300.0,
) -> ActionEngine:
    """Build one exact Home or Memory Maintenance action surface."""

    task_actions = {
        "home": HOME_MAINTENANCE_ACTIONS,
        "memory": MEMORY_MAINTENANCE_ACTIONS,
    }.get(kind)
    if task_actions is None:
        raise MaintenanceContractError(f"Unknown Maintenance task kind: {kind}")
    action_bridge = RuntimeActionBridge()
    try:
        with (
            builtin_action_catalog_root() as core_root,
            maintenance_action_catalog_root() as maintenance_root,
        ):
            builder = ActionEngineBuilder(core_root).add_catalog_root(maintenance_root)
            builder.with_observations(observations)
            builder.with_llm_action_timeout_seconds(llm_action_timeout_seconds)
            builder.include_actions(*COMMON_MAINTENANCE_READ_ACTIONS, *task_actions)
            register_context_actions(
                builder,
                context=context,
                runtime_bridge=RuntimeContextBridge(),
            )
            register_session_actions(
                builder,
                session=session,
                runtime_bridge=RuntimeSessionBridge(),
            )
            if kind == "home":
                register_home_maintenance_actions(
                    builder,
                    controller=home_controller,
                )
            else:
                register_memory_maintenance_actions(
                    builder,
                    controller=memory_controller,
                )
            return builder.build()
    except ConfigError as exc:
        raise action_bridge.from_config_error(exc) from exc
    except ActionError as exc:
        raise action_bridge.startup_failure(
            message=str(exc),
            payload={"error_type": type(exc).__name__},
        ) from exc
