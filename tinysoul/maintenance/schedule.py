"""Daily Maintenance due calculation and missed-work detection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from .config import MaintenanceScheduleSettings
from .day import BusinessDay
from .errors import MaintenanceContractError
from .models import MaintenanceRequest, MaintenanceScope, MaintenanceTrigger


class MaintenanceSchedule:
    """In-memory cursor that emits one Daily Maintenance request when due."""

    def __init__(self, settings: MaintenanceScheduleSettings, *, now: datetime) -> None:
        _require_aware(now)
        self._settings = settings
        local_time = now.timetz().replace(tzinfo=None)
        self._last_emitted = (
            now.date()
            if local_time >= settings.daily_time
            else now.date() - timedelta(days=1)
        )

    def due(self, now: datetime) -> tuple[MaintenanceRequest, ...]:
        _require_aware(now)
        if not self._settings.enabled:
            return ()
        today = now.date()
        local_time = now.timetz().replace(tzinfo=None)
        if self._last_emitted >= today or local_time < self._settings.daily_time:
            return ()
        self._last_emitted = today
        scheduled_for = datetime.combine(
            today,
            self._settings.daily_time,
            tzinfo=now.tzinfo,
        )
        return (
            MaintenanceRequest(
                scope=MaintenanceScope.DAILY,
                trigger=MaintenanceTrigger.SCHEDULED,
                source="scheduler",
                metadata={"scheduled_for": scheduled_for.isoformat()},
            ),
        )

    def seconds_until_next(self, now: datetime) -> float:
        _require_aware(now)
        candidate = datetime.combine(
            now.date(),
            self._settings.daily_time,
            tzinfo=now.tzinfo,
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return max(0.05, (candidate - now).total_seconds())


def missed_memory_days(
    closed_days: Iterable[BusinessDay],
    *,
    eligible: Callable[[BusinessDay], bool],
) -> tuple[BusinessDay, ...]:
    """Return authoritative closed days whose Memory work remains eligible."""

    result = tuple(day for day in sorted(set(closed_days)) if eligible(day))
    if any(not isinstance(day, BusinessDay) for day in result):
        raise MaintenanceContractError("Missed-work catalog contains an invalid day")
    return result


def _require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MaintenanceContractError(
            "Maintenance schedule requires a timezone-aware datetime"
        )
