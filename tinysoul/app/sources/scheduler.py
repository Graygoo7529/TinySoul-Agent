"""App-owned wall-clock scheduler that only submits typed Program events."""

from __future__ import annotations

from datetime import datetime, time as WallTime, timedelta
from threading import Event, RLock, Thread, current_thread
from typing import Protocol

from tinysoul.maintenance import (
    BusinessClock,
    BusinessDay,
    IanaBusinessClock,
    ProgramWorkMode,
)

from ..program import ProgramInputEvent

from ..config import SchedulerSettings
from ..errors import AppContractError


class ProgramEventSink(Protocol):
    def submit_event(self, event: ProgramInputEvent) -> None: ...


class ProgramEventSource(Protocol):
    def start(self, sink: ProgramEventSink) -> None: ...

    def stop(self) -> None: ...


class MaintenanceSchedule:
    """In-memory cursor that emits at most the current day's due events."""

    def __init__(self, settings: SchedulerSettings, *, now: datetime) -> None:
        _require_aware(now)
        self._settings = settings
        previous = now.date() - timedelta(days=1)
        local_time = now.timetz().replace(tzinfo=None)
        self._daily_day = now.date()
        self._home_day = (
            now.date()
            if local_time >= settings.home_maintenance_time
            else previous
        )
        self._memory_day = (
            now.date()
            if local_time >= settings.memory_maintenance_time
            else previous
        )

    def due(self, now: datetime) -> tuple[ProgramInputEvent, ...]:
        _require_aware(now)
        today = now.date()
        local_time = now.timetz().replace(tzinfo=None)
        events: list[ProgramInputEvent] = []
        if self._daily_day < today:
            events.append(
                ProgramInputEvent.daily_rollover(
                    source="scheduler",
                    metadata={"scheduled_for": _scheduled_at(now, WallTime())},
                )
            )
            self._daily_day = today
        if (
            self._home_day < today
            and local_time >= self._settings.home_maintenance_time
        ):
            events.append(
                ProgramInputEvent.home_maintenance(
                    mode=ProgramWorkMode.AUTOMATIC,
                    source="scheduler",
                    metadata={
                        "scheduled_for": _scheduled_at(
                            now,
                            self._settings.home_maintenance_time,
                        )
                    },
                )
            )
            self._home_day = today
        if (
            self._memory_day < today
            and local_time >= self._settings.memory_maintenance_time
        ):
            events.append(
                ProgramInputEvent.memory_maintenance(
                    mode=ProgramWorkMode.AUTOMATIC,
                    target_day=BusinessDay(today - timedelta(days=1)),
                    source="scheduler",
                    metadata={
                        "scheduled_for": _scheduled_at(
                            now,
                            self._settings.memory_maintenance_time,
                        )
                    },
                )
            )
            self._memory_day = today
        return tuple(events)

    def seconds_until_next(self, now: datetime) -> float:
        _require_aware(now)
        candidates = (
            _next_after(now, WallTime()),
            _next_after(now, self._settings.home_maintenance_time),
            _next_after(now, self._settings.memory_maintenance_time),
        )
        return max(0.05, min((value - now).total_seconds() for value in candidates))


class MaintenanceScheduler:
    """Background source for Daily Rollover and automatic Maintenance events."""

    def __init__(
        self,
        settings: SchedulerSettings,
        *,
        clock: BusinessClock | None = None,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self._settings = settings
        self._clock = clock or IanaBusinessClock(timezone)
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = RLock()

    @property
    def running(self) -> bool:
        with self._lock:
            thread = self._thread
            return thread is not None and thread.is_alive()

    def start(self, sink: ProgramEventSink) -> None:
        with self._lock:
            if self.running:
                return
            self._stop_event.clear()
            schedule = MaintenanceSchedule(self._settings, now=self._clock.now())
            self._thread = Thread(
                target=self._run,
                args=(sink, schedule),
                name="tinysoul-maintenance-scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not current_thread():
            thread.join(timeout=2.0)

    def _run(self, sink: ProgramEventSink, schedule: MaintenanceSchedule) -> None:
        while not self._stop_event.is_set():
            now = self._clock.now()
            for event in schedule.due(now):
                sink.submit_event(event)
            if self._stop_event.wait(schedule.seconds_until_next(now)):
                return


def _scheduled_at(now: datetime, value: WallTime) -> str:
    return datetime.combine(now.date(), value, tzinfo=now.tzinfo).isoformat()


def _next_after(now: datetime, value: WallTime) -> datetime:
    candidate = datetime.combine(now.date(), value, tzinfo=now.tzinfo)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _require_aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AppContractError("Maintenance scheduler requires an aware datetime")
