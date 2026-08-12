"""Background adapter that submits scheduled Maintenance requests."""

from __future__ import annotations

from collections.abc import Callable
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
        settings_provider: (
            Callable[[], tuple[MaintenanceScheduleSettings, str]] | None
        ) = None,
    ) -> None:
        self._settings = settings
        self._clock = clock or IanaBusinessClock(timezone)
        self._stop_event = Event()
        self._refresh_event = Event()
        self._thread: Thread | None = None
        self._lock = RLock()
        self._settings_provider = settings_provider

    def refresh(self) -> None:
        """Wake the stable scheduler so it re-reads current Generation settings."""

        self._refresh_event.set()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, sink: ProgramRequestSink) -> None:
        with self._lock:
            if self.running:
                return
            self._stop_event.clear()
            self._refresh_event.clear()
            self._thread = Thread(
                target=self._run,
                args=(sink,),
                name="tinysoul-maintenance-scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
            self._refresh_event.set()
        if thread is not None and thread is not current_thread():
            thread.join(timeout=2.0)

    def _run(
        self,
        sink: ProgramRequestSink,
    ) -> None:
        settings, timezone = self._current_settings()
        clock = (
            self._clock
            if self._settings_provider is None
            else IanaBusinessClock(timezone)
        )
        schedule = MaintenanceSchedule(settings, now=clock.now())
        while not self._stop_event.is_set():
            current_settings, current_timezone = self._current_settings()
            if current_settings != settings or current_timezone != timezone:
                settings = current_settings
                timezone = current_timezone
                clock = (
                    self._clock
                    if self._settings_provider is None
                    else IanaBusinessClock(timezone)
                )
                schedule = MaintenanceSchedule(settings, now=clock.now())
            now = clock.now()
            for request in schedule.due(now):
                sink.submit_request(request)
            wait_seconds = schedule.seconds_until_next(now)
            if self._refresh_event.wait(wait_seconds):
                self._refresh_event.clear()
            if self._stop_event.is_set():
                return

    def _current_settings(self) -> tuple[MaintenanceScheduleSettings, str]:
        if self._settings_provider is None:
            return self._settings, ""
        return self._settings_provider()
