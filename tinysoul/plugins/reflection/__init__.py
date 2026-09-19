"""Daily archive lifecycle and autonomous reflection orchestration."""

from __future__ import annotations

from .config import (
    ReflectionScheduleSettings,
    ReflectionSettings,
    parse_reflection_settings,
)
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
    "parse_reflection_settings",
]
