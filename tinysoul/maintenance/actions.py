"""Explicit per-Turn ActionEngine views for Maintenance isolation."""

from __future__ import annotations

from tinysoul.action import ActionEngine

from .errors import MaintenanceContractError
from .home import HOME_MAINTENANCE_ACTIONS
from .memory import MEMORY_MAINTENANCE_ACTIONS

COMMON_MAINTENANCE_READ_ACTIONS = (
    "core.context.inspect",
    "core.session.inspect",
)

MAINTENANCE_ACTIONS = tuple(
    dict.fromkeys((*HOME_MAINTENANCE_ACTIONS, *MEMORY_MAINTENANCE_ACTIONS))
)


def user_action_view(action: ActionEngine) -> ActionEngine:
    """Exclude all framework-only Maintenance actions from a User Turn."""

    return action.view(
        tuple(
            name
            for domain, name in action.action_identifiers()
            if domain != "maintenance"
        )
    )


def maintenance_action_view(action: ActionEngine, *, kind: str) -> ActionEngine:
    """Compose common read-only inspection with one task's exact actions."""

    task_actions = {
        "home": HOME_MAINTENANCE_ACTIONS,
        "memory": MEMORY_MAINTENANCE_ACTIONS,
    }.get(kind)
    if task_actions is None:
        raise MaintenanceContractError(f"Unknown Maintenance task kind: {kind}")
    available = {name for _domain, name in action.action_identifiers()}
    requested = tuple(
        name
        for name in (*COMMON_MAINTENANCE_READ_ACTIONS, *task_actions)
        if name in available
    )
    missing = set(
        (*COMMON_MAINTENANCE_READ_ACTIONS, *task_actions)
    ) - set(requested)
    if missing:
        raise MaintenanceContractError(
            "Maintenance Action Catalog is incomplete: " + ", ".join(sorted(missing))
        )
    return action.view(tuple(dict.fromkeys(requested)))
