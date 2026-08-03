"""Background adapter that submits scheduled Maintenance requests."""

from __future__ import annotations

from threading import Event, RLock, Thread, current_thread
from typing import Protocol

from tinysoul.app.requests import AppRequest
from tinysoul.maintenance import (
    BusinessClock,
    IanaBusinessClock,
    MaintenanceSchedule,
    MaintenanceScheduleSettings,
)


class ProgramRequestSink(Protocol):
    def submit_request(self, request: AppRequest) -> None: ...


class ProgramRequestSource(Protocol):
    def start(self, sink: ProgramRequestSink) -> None: ...

    def stop(self) -> None: ...


class MaintenanceScheduler:
    """Submit due work without executing or waiting for Maintenance."""

    def __init__(
        self,
        settings: MaintenanceScheduleSettings,
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
            return self._thread is not None and self._thread.is_alive()

    def start(self, sink: ProgramRequestSink) -> None:
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

    def _run(
        self,
        sink: ProgramRequestSink,
        schedule: MaintenanceSchedule,
    ) -> None:
        while not self._stop_event.is_set():
            now = self._clock.now()
            for request in schedule.due(now):
                sink.submit_request(request)
            if self._stop_event.wait(schedule.seconds_until_next(now)):
                return
