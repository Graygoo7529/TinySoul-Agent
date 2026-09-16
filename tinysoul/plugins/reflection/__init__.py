"""Daily archive lifecycle and autonomous maintenance orchestration."""

from __future__ import annotations

from .config import (
    ReflectionScheduleSettings,
    ReflectionSettings,
    parse_maintenance_settings,
)
from .availability import ReflectionAvailabilityStore
from .builder import ReflectionBuilder
from .errors import (
    ReflectionContractError,
    ReflectionError,
    ReflectionInvariantError,
    ReflectionTaskExecutionError,
)
from .failures import ReflectionFailureKind
from .models import (
    ReflectionAvailability,
    ReflectionOutcome,
    ReflectionRequest,
    ReflectionScope,
    ReflectionStatus,
    ReflectionTaskKind,
    ReflectionTaskOutcome,
    ReflectionTaskStatus,
    ReflectionTrigger,
)
from .schedule import ReflectionSchedule
from .runtime_bridge import ReflectionRuntimeBridge

from .engine import ReflectionEngine

__all__ = [
    "ReflectionAvailability",
    "ReflectionAvailabilityStore",
    "ReflectionBuilder",
    "ReflectionContractError",
    "ReflectionEngine",
    "ReflectionError",
    "ReflectionFailureKind",
    "ReflectionInvariantError",
    "ReflectionTaskExecutionError",
    "ReflectionOutcome",
    "ReflectionRequest",
    "ReflectionRuntimeBridge",
    "ReflectionSchedule",
    "ReflectionScheduleSettings",
    "ReflectionScope",
    "ReflectionSettings",
    "ReflectionStatus",
    "ReflectionTaskKind",
    "ReflectionTaskOutcome",
    "ReflectionTaskStatus",
    "ReflectionTrigger",
    "parse_maintenance_settings",
]
