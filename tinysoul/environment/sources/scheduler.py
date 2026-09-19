"""Background adapter that submits scheduled Reflection requests."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, RLock, Thread, current_thread
from typing import Protocol
from ..errors import EnvironmentError

from tinysoul.infra.clock import BusinessClock
from tinysoul.infra.clock import IanaBusinessClock
from tinysoul.plugins.reflection import (
    ReflectionSchedule,
    ReflectionScheduleSettings,
    ReflectionRequest,
)


class AgentRequestSink(Protocol):
    def submit_request(self, request: ReflectionRequest) -> bool: ...


class AgentRequestSource(Protocol):
    def start(self, sink: AgentRequestSink) -> None: ...

    def stop(self) -> None: ...


class ReflectionScheduler:
    """Submit due work without executing or waiting for Reflection."""

    def __init__(
        self,
        settings: ReflectionScheduleSettings,
        *,
        clock: BusinessClock | None = None,
        timezone: str = "Asia/Shanghai",
        settings_provider: (
            Callable[[], tuple[ReflectionScheduleSettings, str]] | None
        ) = None,
    ) -> None:
        self._settings = settings
        self._clock = clock or IanaBusinessClock(timezone)
        self._stop_event = Event()
        self._refresh_event = Event()
        self._thread: Thread | None = None
        self._lock = RLock()
        self._settings_provider = settings_provider
        self._error: Exception | None = None

    def refresh(self) -> None:
        """Wake the stable scheduler so it re-reads current Generation settings."""

        self._refresh_event.set()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, sink: AgentRequestSink) -> None:
        with self._lock:
            if self.running:
                return
            self._stop_event.clear()
            self._refresh_event.clear()
            self._error = None
            self._thread = Thread(
                target=self._serve,
                args=(sink,),
                name="tinysoul-reflection-scheduler",
                daemon=False,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
            self._refresh_event.set()
        if thread is not None and thread is not current_thread():
            thread.join(timeout=2.0)
            if thread.is_alive():
                raise EnvironmentError("Reflection scheduler did not stop")
        self._thread = None
        if self._error is not None:
            raise EnvironmentError("Reflection scheduler failed") from self._error

    def _serve(self, sink: AgentRequestSink) -> None:
        try:
            self._run(sink)
        except Exception as exc:
            self._error = exc

    def _run(
        self,
        sink: AgentRequestSink,
    ) -> None:
        settings, timezone = self._current_settings()
        clock = (
            self._clock
            if self._settings_provider is None
            else IanaBusinessClock(timezone)
        )
        schedule = ReflectionSchedule(settings, now=clock.now())
        pending: tuple[ReflectionRequest, ...] = ()
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
                schedule = ReflectionSchedule(settings, now=clock.now())
            now = clock.now()
            pending = pending or schedule.due(now)
            pending = tuple(
                request for request in pending if not sink.submit_request(request)
            )
            wait_seconds = (
                min(1.0, schedule.seconds_until_next(now))
                if pending
                else schedule.seconds_until_next(now)
            )
            if self._refresh_event.wait(wait_seconds):
                self._refresh_event.clear()
            if self._stop_event.is_set():
                return

    def _current_settings(self) -> tuple[ReflectionScheduleSettings, str]:
        if self._settings_provider is None:
            return self._settings, ""
        return self._settings_provider()
