"""Archive owner: deterministic rollover journal and frozen-day catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from tinysoul.infra.concurrency import ReadWriteLock
from tinysoul.infra.time import CalendarDay

from ..errors import ArchiveContractError, ArchiveInvariantError


from ..projection import ArchiveProjection


@dataclass(frozen=True)
class DailyTransitionOutcome:
    active_day: CalendarDay
    archives: tuple[ArchiveProjection, ...] = field(default_factory=tuple)
    resumed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.active_day, CalendarDay):
            raise ArchiveContractError("Daily transition active day is invalid")
        if any(not isinstance(item, ArchiveProjection) for item in self.archives):
            raise ArchiveContractError("Daily transition archives are invalid")
        days = tuple(item.day for item in self.archives)
        if len(days) != len(set(days)):
            raise ArchiveContractError("Daily transition archive days must be unique")
        if any(day >= self.active_day for day in days):
            raise ArchiveContractError("Daily transition archived day must be closed")
        object.__setattr__(self, "archives", tuple(self.archives))


class ActiveDayLease:
    """Hold shared rollover exclusion while accessing active-day modules.

    The lease is the read side of the coordinator lock: any number of
    active-day users (a running User Turn, Endpoint status and Workspace
    requests) may hold it concurrently. Only the daily rollover takes the
    exclusive write side, so lease holders never block each other.
    """

    def __init__(
        self,
        *,
        lock: ReadWriteLock,
        session: SessionDailyLifecycle,
        workspace: WorkspaceDailyLifecycle,
        memory: ActiveMemoryDailyLifecycle,
    ) -> None:
        self._lock = lock
        self._session = session
        self._workspace = workspace
        self._memory = memory
        self._entered = False

    def __enter__(self) -> CalendarDay:
        self._lock.acquire_read()
        self._entered = True
        try:
            session_day = self._session.active_day
            workspace_day = self._workspace.active_day
            memory_day = self._memory.active_day()
            if session_day is None or workspace_day is None:
                raise ArchiveInvariantError("Daily active day is not initialized")
            if session_day != workspace_day or session_day != memory_day:
                raise ArchiveInvariantError(
                    "Session, Workspace, and Memory active days disagree"
                )
            return session_day
        except Exception:
            self._release()
            raise

    def __exit__(
        self,
        exception_type: object,
        exception: object,
        traceback: object,
    ) -> None:
        self._release()

    def _release(self) -> None:
        if self._entered:
            self._entered = False
            self._lock.release_read()


class SessionDailyLifecycle(Protocol):
    @property
    def root(self) -> Path: ...

    @property
    def active_day(self) -> CalendarDay | None: ...

    def initialize_day(self, day: CalendarDay) -> None: ...

    def archive_day(self, day: CalendarDay, *, target: Path) -> None: ...

    def reconcile_active(self) -> object: ...


class WorkspaceDailyLifecycle(Protocol):
    @property
    def root(self) -> Path: ...

    @property
    def active_day(self) -> CalendarDay | None: ...

    def initialize_day(self, day: CalendarDay) -> object: ...

    def archive_day(
        self,
        day: CalendarDay,
        *,
        workspace_target: Path,
        trash_target: Path,
    ) -> None: ...


class ActiveMemoryDailyLifecycle(Protocol):
    @property
    def root(self) -> Path: ...

    @property
    def active_session_root(self) -> Path | None: ...

    def active_day(self) -> CalendarDay: ...

    def initialize_active_day(self, day: CalendarDay) -> object: ...

    def validate_active_day(self, day: CalendarDay) -> object: ...

    def validate_archived_active(
        self, day: CalendarDay, session_archive_root: Path
    ) -> object: ...
