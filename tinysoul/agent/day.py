"""Agent-owned deterministic day preparation before any root work."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from collections.abc import Iterator
from typing import Protocol

from tinysoul.infra.clock import BusinessClock
from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.archive import DailyLifecycleCoordinator, DailyTransitionOutcome
from tinysoul.plugins.archive.errors import ArchiveError
from tinysoul.plugins.archive.runtime_bridge import RuntimeArchiveBridge
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.plugins.memory.errors import MemoryError
from tinysoul.plugins.memory.runtime_bridge import RuntimeMemoryBridge
from tinysoul.runtime import RunScope


class DayLifecycle(Protocol):
    def current_day(self) -> CalendarDay: ...

    def preflight(self, *, scope: RunScope) -> DailyTransitionOutcome: ...

    def active_day_lease(self) -> AbstractContextManager[CalendarDay]: ...


class AgentDayCoordinator:
    """Coordinate storage owners; model-based Reflection never advances the day."""

    def __init__(self, archive: DailyLifecycleCoordinator, memory: MemoryEngine, clock: BusinessClock) -> None:
        self._archive = archive
        self._memory = memory
        self._clock = clock

    @contextmanager
    def active_day_lease(self) -> Iterator[CalendarDay]:
        try:
            with self._archive.active_day_lease() as day:
                yield day
        except ArchiveError as exc:
            raise RuntimeArchiveBridge().from_archive_error(exc) from exc

    def current_day(self) -> CalendarDay:
        return CalendarDay(self._clock.now().date())

    def preflight(self, *, scope: RunScope) -> DailyTransitionOutcome:
        try:
            self._memory.rebuild_catalog()
        except MemoryError as exc:
            raise RuntimeMemoryBridge().startup_failure(
                message="Memory recovery could not prepare the active day.",
                payload={"error_type": type(exc).__name__},
            ) from exc
        try:
            now = self._clock.now()
            return self._archive.ensure_active_day(CalendarDay(now.date()), now=now, scope=scope)
        except ArchiveError as exc:
            raise RuntimeArchiveBridge().from_archive_error(exc, preparing=True) from exc
