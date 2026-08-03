"""Daily lifecycle and autonomous maintenance domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .archive import (
    ActiveDayLease,
    DailyLifecycleCoordinator,
    DailyTransitionJournal,
    DailyTransitionOutcome,
    DailyTransitionStep,
)
from .config import (
    MaintenanceScheduleSettings,
    MaintenanceSettings,
    parse_maintenance_settings,
)
from .day import BusinessClock, BusinessDay, IanaBusinessClock
from .errors import MaintenanceContractError, MaintenanceError, MaintenanceInvariantError
from .failures import MaintenanceFailureKind
from .outcomes import (
    MaintenanceOutcome,
    MaintenanceStatus,
    MaintenanceTaskKind,
    MaintenanceTaskOutcome,
    MaintenanceTaskStatus,
)
from .request import MaintenanceRequest, MaintenanceScope, MaintenanceTrigger
if TYPE_CHECKING:
    from .actions import (
        MAINTENANCE_ACTIONS,
        MAINTENANCE_HOME_ACTIONS,
        MAINTENANCE_MEMORY_ACTIONS,
        MaintenanceActionController,
        MaintenanceCompletionDetector,
        MaintenanceTaskResult,
        maintenance_action_view,
        register_maintenance_actions,
        user_action_view,
    )
    from .service import MaintenanceAvailability, ProgramMaintenanceRunner

__all__ = [
    "ActiveDayLease",
    "BusinessClock",
    "BusinessDay",
    "DailyLifecycleCoordinator",
    "DailyTransitionJournal",
    "DailyTransitionOutcome",
    "DailyTransitionStep",
    "IanaBusinessClock",
    "MAINTENANCE_ACTIONS",
    "MAINTENANCE_HOME_ACTIONS",
    "MAINTENANCE_MEMORY_ACTIONS",
    "MaintenanceActionController",
    "MaintenanceAvailability",
    "MaintenanceContractError",
    "MaintenanceCompletionDetector",
    "MaintenanceError",
    "MaintenanceFailureKind",
    "MaintenanceInvariantError",
    "MaintenanceOutcome",
    "MaintenanceRequest",
    "MaintenanceScheduleSettings",
    "MaintenanceScope",
    "MaintenanceSettings",
    "MaintenanceStatus",
    "MaintenanceTaskKind",
    "MaintenanceTaskOutcome",
    "MaintenanceTaskResult",
    "MaintenanceTaskStatus",
    "MaintenanceTrigger",
    "ProgramMaintenanceRunner",
    "parse_maintenance_settings",
    "maintenance_action_view",
    "register_maintenance_actions",
    "user_action_view",
]


def __getattr__(name: str) -> object:
    if name in {
        "MAINTENANCE_ACTIONS",
        "MAINTENANCE_HOME_ACTIONS",
        "MAINTENANCE_MEMORY_ACTIONS",
        "MaintenanceActionController",
        "MaintenanceCompletionDetector",
        "MaintenanceTaskResult",
        "maintenance_action_view",
        "register_maintenance_actions",
        "user_action_view",
    }:
        from . import actions

        return getattr(actions, name)
    if name in {"MaintenanceAvailability", "ProgramMaintenanceRunner"}:
        from .service import MaintenanceAvailability, ProgramMaintenanceRunner

        return {
            "MaintenanceAvailability": MaintenanceAvailability,
            "ProgramMaintenanceRunner": ProgramMaintenanceRunner,
        }[name]
    raise AttributeError(name)
