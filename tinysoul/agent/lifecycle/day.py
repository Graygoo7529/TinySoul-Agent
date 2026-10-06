"""Agent-owned deterministic day preparation before any root work."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
import json
from pathlib import Path
from typing import Protocol

from tinysoul.infra.clock import CalendarClock
from tinysoul.infra.concurrency import AsyncCloser, AsyncReadWriteLock, JoinedOperations
from tinysoul.infra.time import CalendarDay
from tinysoul.infra.filesystem import atomic_write_text
from tinysoul.kernel.identity import TurnIdentity, TurnIdentityError
from tinysoul.plugins.archive import DailyLifecycleCoordinator, DailyTransitionOutcome
from tinysoul.plugins.archive.errors import ArchiveError
from tinysoul.plugins.archive.projection import ArchiveProjection
from tinysoul.plugins.archive.runtime_bridge import RuntimeArchiveBridge
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.plugins.memory.errors import MemoryError
from tinysoul.plugins.memory.runtime_bridge import RuntimeMemoryBridge
from tinysoul.runtime import RunScope

from ..errors import AgentInvariantError
from ..runtime_bridge import RuntimeAgentBridge
from .sources import GenerationSources


class DayLifecycle(Protocol):
    @property
    def active_day(self) -> CalendarDay | None: ...

    def current_day(self) -> CalendarDay: ...

    async def preflight(self, *, scope: RunScope) -> DailyTransitionOutcome: ...

    def active_day_lease(self) -> AbstractAsyncContextManager[CalendarDay]: ...

    def allocate_turn(self, day: CalendarDay) -> str: ...


class AgentDayCoordinator:
    """Coordinate storage owners; model-based Reflection never advances the day."""

    def __init__(
        self,
        archive: DailyLifecycleCoordinator,
        memory: MemoryEngine,
        clock: CalendarClock,
        *,
        turn_sequence_path: Path,
        active_day: CalendarDay | None = None,
        release_day: tuple[AsyncCloser, ...] = (),
    ) -> None:
        self._archive = archive
        self._memory = memory
        self._clock = clock
        self._lock = AsyncReadWriteLock()
        self._active_day = active_day
        self._release_day = release_day
        self._sources: GenerationSources | None = None
        self._turn_sequence_path = turn_sequence_path

    def allocate_turn(self, day: CalendarDay) -> str:
        """Advance one persisted high-water mark under the root scheduler's lease."""
        if day != self._active_day:
            raise AgentInvariantError("Turn allocation requires the active day lease")
        try:
            previous = None
            if self._turn_sequence_path.exists():
                value = json.loads(self._turn_sequence_path.read_text(encoding="utf-8"))
                if not isinstance(value, dict) or set(value) != {"day", "sequence"}:
                    raise TurnIdentityError("Invalid Turn sequence state")
                previous = TurnIdentity.parse(f"{value['day']}/{value['sequence']}")
                if previous.day > day:
                    raise TurnIdentityError(
                        "Turn allocation cannot move to an earlier day"
                    )
            identity = TurnIdentity(
                day, previous.sequence + 1 if previous and previous.day == day else 1
            )
            atomic_write_text(
                self._turn_sequence_path,
                json.dumps({"day": str(day), "sequence": identity.sequence}),
            )
            return str(identity)
        except (OSError, json.JSONDecodeError, TurnIdentityError) as exc:
            raise RuntimeAgentBridge().startup_failure(
                message="Turn identity could not be allocated.",
                payload={
                    "operation": "allocate_turn",
                    "error_type": type(exc).__name__,
                },
            ) from exc

    def bind_sources(self, sources: GenerationSources) -> None:
        self._sources = sources

    def archive_for(self, day: CalendarDay) -> ArchiveProjection | None:
        return self._archive.archive_for(day)

    def archived_days(
        self, *, before: CalendarDay | None = None, limit: int = 100
    ) -> tuple[CalendarDay, ...]:
        return self._archive.archived_days(before=before, limit=limit)

    @asynccontextmanager
    async def active_day_lease(self) -> AsyncIterator[CalendarDay]:
        async with self._lock.read_locked():
            if self._active_day is None:
                raise AgentInvariantError(
                    "Active day requires deterministic preparation"
                )
            yield self._active_day

    @property
    def active_day(self) -> CalendarDay | None:
        return self._active_day

    def current_day(self) -> CalendarDay:
        return CalendarDay(self._clock.now().date())

    async def preflight(self, *, scope: RunScope) -> DailyTransitionOutcome:
        changing = self._active_day != self.current_day()
        if changing and self._sources is not None:
            await self._sources.pause()
        try:
            if changing and self._active_day is not None:
                operations = JoinedOperations()
                for release in self._release_day:
                    await operations.run_async(release)
                operations.check_cancelled()
            return await self._preflight(scope=scope)
        finally:
            if changing and self._sources is not None:
                await self._sources.resume()

    async def _preflight(self, *, scope: RunScope) -> DailyTransitionOutcome:
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
            return self._archive.ensure_active_day(
                CalendarDay(now.date()), now=now, scope=scope
            )
        except ArchiveError as exc:
            raise RuntimeArchiveBridge().from_archive_error(
                exc, preparing=True
            ) from exc
