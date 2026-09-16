"""Daily Reflection due calculation."""

from __future__ import annotations

from datetime import datetime, timedelta

from .config import ReflectionScheduleSettings
from .errors import ReflectionContractError
from .models import ReflectionRequest, ReflectionScope, ReflectionTrigger


class ReflectionSchedule:
    """In-memory cursor that emits one Daily Reflection request when due."""

    def __init__(self, settings: ReflectionScheduleSettings, *, now: datetime) -> None:
        _require_aware(now)
        self._settings = settings
        local_time = now.timetz().replace(tzinfo=None)
        self._last_emitted = (
            now.date()
            if local_time >= settings.daily_time
            else now.date() - timedelta(days=1)
        )

    def due(self, now: datetime) -> tuple[ReflectionRequest, ...]:
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
            ReflectionRequest(
                scope=ReflectionScope.DAILY,
                trigger=ReflectionTrigger.SCHEDULED,
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


def _require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ReflectionContractError(
            "Reflection schedule requires a timezone-aware datetime"
        )
