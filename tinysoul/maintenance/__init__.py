"""Daily archive lifecycle and autonomous maintenance orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .archive import (
    ActiveDayLease,
    ArchiveProjection,
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
from .models import (
    MaintenanceAvailability,
    MaintenanceOutcome,
    MaintenancePlan,
    MaintenanceRequest,
    MaintenanceScope,
    MaintenanceStatus,
    MaintenanceTaskKind,
    MaintenanceTaskOutcome,
    MaintenanceTaskPlan,
    MaintenanceTaskStatus,
    MaintenanceTrigger,
)
from .schedule import MaintenanceSchedule

if TYPE_CHECKING:
    from .engine import MaintenanceEngine

__all__ = [
    "ActiveDayLease",
    "ArchiveProjection",
    "BusinessClock",
    "BusinessDay",
    "DailyLifecycleCoordinator",
    "DailyTransitionJournal",
    "DailyTransitionOutcome",
    "DailyTransitionStep",
    "IanaBusinessClock",
    "MaintenanceAvailability",
    "MaintenanceContractError",
    "MaintenanceEngine",
    "MaintenanceError",
    "MaintenanceFailureKind",
    "MaintenanceInvariantError",
    "MaintenanceOutcome",
    "MaintenancePlan",
    "MaintenanceRequest",
    "MaintenanceSchedule",
    "MaintenanceScheduleSettings",
    "MaintenanceScope",
    "MaintenanceSettings",
    "MaintenanceStatus",
    "MaintenanceTaskKind",
    "MaintenanceTaskOutcome",
    "MaintenanceTaskPlan",
    "MaintenanceTaskStatus",
    "MaintenanceTrigger",
    "parse_maintenance_settings",
]


def __getattr__(name: str) -> object:
    if name == "MaintenanceEngine":
        from .engine import MaintenanceEngine

        return MaintenanceEngine
    raise AttributeError(name)
