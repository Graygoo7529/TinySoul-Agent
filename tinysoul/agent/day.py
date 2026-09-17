"""Agent-owned deterministic day preparation before any root work."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager, asynccontextmanager
from collections.abc import AsyncIterator
from typing import Protocol

from tinysoul.infra.clock import BusinessClock
from tinysoul.infra.concurrency import AsyncReadWriteLock, JoinedOperations
from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.archive import DailyLifecycleCoordinator, DailyTransitionOutcome
from tinysoul.plugins.archive.errors import ArchiveError
from tinysoul.plugins.archive.runtime_bridge import RuntimeArchiveBridge
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.plugins.memory.errors import MemoryError
from tinysoul.plugins.memory.runtime_bridge import RuntimeMemoryBridge
from tinysoul.runtime import RunScope
from .errors import AgentInvariantError


class DayLifecycle(Protocol):
    @property
    def active_day(self) -> CalendarDay | None: ...

    def current_day(self) -> CalendarDay: ...

    async def preflight(self, *, scope: RunScope) -> DailyTransitionOutcome: ...

    def active_day_lease(self) -> AbstractAsyncContextManager[CalendarDay]: ...


class AgentDayCoordinator:
    """Coordinate storage owners; model-based Reflection never advances the day."""

    def __init__(self, archive: DailyLifecycleCoordinator, memory: MemoryEngine, clock: BusinessClock,
                 *, active_day: CalendarDay | None = None) -> None:
        self._archive = archive
        self._memory = memory
        self._clock = clock
        self._lock = AsyncReadWriteLock()
        self._active_day = active_day

    @asynccontextmanager
    async def active_day_lease(self) -> AsyncIterator[CalendarDay]:
        async with self._lock.read_locked():
            if self._active_day is None:
                raise AgentInvariantError("Active day requires deterministic preparation")
            yield self._active_day

    @property
    def active_day(self) -> CalendarDay | None:
        return self._active_day

    def current_day(self) -> CalendarDay:
        return CalendarDay(self._clock.now().date())

    async def preflight(self, *, scope: RunScope) -> DailyTransitionOutcome:
        async with self._lock.write_locked():
            operation = JoinedOperations()
            transition = await operation.run(lambda: self._prepare(scope))
            self._active_day = transition.active_day
            operation.check_cancelled()
            return transition

    def _prepare(self, scope: RunScope) -> DailyTransitionOutcome:
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
