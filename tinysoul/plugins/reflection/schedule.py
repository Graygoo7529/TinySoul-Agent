"""Daily Reflection due calculation."""

from __future__ import annotations

from datetime import datetime, timedelta
from collections.abc import Awaitable, Callable
from typing import Protocol

from tinysoul.infra.clock import CalendarClock
from tinysoul.infra.time import CalendarDay
from tinysoul.runtime.events import EnvironmentEvent, EventKind
from tinysoul.runtime.sources import EventSink, SourceState, SourceStatus

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
                scheduled_day=CalendarDay(today),
                request_id=f"reflection.schedule:{today}",
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


class ReflectionTimer(Protocol):
    async def start(self, tick: Callable[[], Awaitable[float]]) -> None: ...

    async def stop(self) -> None: ...


class ReflectionScheduler:
    """Plugin-owned due policy and typed trigger over an injected timer."""

    def __init__(self, settings: ReflectionScheduleSettings, *, clock: CalendarClock,
                 timer: ReflectionTimer,
                 submit: Callable[[ReflectionRequest], Awaitable[bool]]) -> None:
        self._settings = settings
        self._clock = clock
        self._timer = timer
        self._submit = submit
        self._schedule: ReflectionSchedule | None = None
        self._pending: tuple[ReflectionRequest, ...] = ()
        self._publish: EventSink | None = None
        self._status = SourceStatus("reflection.schedule", SourceState.STOPPED,
                                    topics=("reflection.due",))

    @property
    def status(self) -> SourceStatus:
        return self._status

    async def start(self, publish: EventSink) -> None:
        self._publish = publish
        if self._schedule is None:
            self._schedule = ReflectionSchedule(self._settings, now=self._clock.now())
        self._status = SourceStatus("reflection.schedule",
            SourceState.RUNNING if self._settings.enabled else SourceState.DISABLED,
            topics=("reflection.due",))
        if self._settings.enabled:
            await self._timer.start(self.tick)

    async def tick(self) -> float:
        schedule = self._schedule
        if schedule is None or self._publish is None:
            raise ReflectionContractError("Reflection timer is not active")
        now = self._clock.now()
        self._pending = self._pending or schedule.due(now)
        remaining: list[ReflectionRequest] = []
        for request in self._pending:
            # Admission uses the typed request port, independently of Turn
            # subscriptions. Retry the same frozen due fact when the queue is full.
            if not await self._submit(request):
                remaining.append(request)
                continue
            await self._publish(EnvironmentEvent(
                EventKind.TIMER, {"scheduled_day": str(request.scheduled_day)},
                event_id=request.request_id, topic="reflection.due", source="reflection.schedule",
            ))
        self._pending = tuple(remaining)
        delay = schedule.seconds_until_next(now)
        return min(1.0, delay) if self._pending else delay

    async def stop(self) -> None:
        await self._timer.stop()
        self._publish = None
        self._status = SourceStatus("reflection.schedule", SourceState.STOPPED,
                                    topics=("reflection.due",))
