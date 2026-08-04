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
from .availability import MaintenanceAvailabilityStore
from .builder import MaintenanceBuilder
from .day import BusinessClock, IanaBusinessClock
from .errors import (
    MaintenanceContractError,
    MaintenanceError,
    MaintenanceInvariantError,
    MaintenanceTaskExecutionError,
)
from .failures import MaintenanceFailureKind
from .models import (
    MaintenanceAvailability,
    MaintenanceOutcome,
    MaintenanceRequest,
    MaintenanceScope,
    MaintenanceStatus,
    MaintenanceTaskKind,
    MaintenanceTaskOutcome,
    MaintenanceTaskStatus,
    MaintenanceTrigger,
)
from .schedule import MaintenanceSchedule
from .runtime_bridge import MaintenanceRuntimeBridge

if TYPE_CHECKING:
    from .engine import MaintenanceEngine

__all__ = [
    "ActiveDayLease",
    "ArchiveProjection",
    "BusinessClock",
    "DailyLifecycleCoordinator",
    "DailyTransitionJournal",
    "DailyTransitionOutcome",
    "DailyTransitionStep",
    "IanaBusinessClock",
    "MaintenanceAvailability",
    "MaintenanceAvailabilityStore",
    "MaintenanceBuilder",
    "MaintenanceContractError",
    "MaintenanceEngine",
    "MaintenanceError",
    "MaintenanceFailureKind",
    "MaintenanceInvariantError",
    "MaintenanceTaskExecutionError",
    "MaintenanceOutcome",
    "MaintenanceRequest",
    "MaintenanceRuntimeBridge",
    "MaintenanceSchedule",
    "MaintenanceScheduleSettings",
    "MaintenanceScope",
    "MaintenanceSettings",
    "MaintenanceStatus",
    "MaintenanceTaskKind",
    "MaintenanceTaskOutcome",
    "MaintenanceTaskStatus",
    "MaintenanceTrigger",
    "parse_maintenance_settings",
]


def __getattr__(name: str) -> object:
    if name == "MaintenanceEngine":
        from .engine import MaintenanceEngine

        return MaintenanceEngine
    raise AttributeError(name)
