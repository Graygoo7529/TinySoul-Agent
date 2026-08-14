"""Maintenance-owned ActionEngine assembly."""

from __future__ import annotations

from tinysoul.action import (
    ActionCatalog,
    ActionCatalogLoader,
    ActionEngine,
    ActionEngineBuilder,
    ActionError,
    LoadedActionCatalog,
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
    action_catalog: LoadedActionCatalog,
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
        with maintenance_action_catalog_root() as maintenance_root:
            maintenance_catalog = ActionCatalogLoader().load(maintenance_root)
            combined = LoadedActionCatalog(
                catalog=ActionCatalog(
                    domains=(
                        *action_catalog.catalog.domains(),
                        *maintenance_catalog.domains(),
                    ),
                    actions=(
                        *action_catalog.catalog.actions(),
                        *maintenance_catalog.actions(),
                    ),
                ),
                documents=action_catalog.documents,
            )
            builder = ActionEngineBuilder(combined)
            builder.with_observations(observations)
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
