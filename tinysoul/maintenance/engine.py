"""Single orchestration facade for deterministic and Turn-based maintenance."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from threading import RLock
from typing import Protocol

from tinysoul.home import AgentHomeIOError, AgentHomeInvariantError
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import BusinessDay
from tinysoul.memory import MemoryIOError, MemoryInvariantError
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunScope,
    emit_observation,
    observation_enabled,
)
from tinysoul.session import SessionIOError, SessionInvariantError
from tinysoul.workspace import WorkspaceIOError, WorkspaceInvariantError

from .archive import ArchiveProjection, DailyTransitionOutcome
from .availability import MaintenanceAvailabilityStore
from .day import BusinessClock
from .errors import MaintenanceInvariantError, MaintenanceTaskExecutionError
from .models import (
    MaintenanceAvailability,
    MaintenanceOutcome,
    MaintenanceRequest,
    MaintenanceScope,
    MaintenanceStatus,
    MaintenanceTaskKind,
    MaintenanceTaskOutcome,
    MaintenanceTaskStatus,
)


class ArchiveMaintenance(Protocol):
    """Archive lifecycle and catalog operations used by the facade."""

    def active_day_lease(self) -> AbstractContextManager[BusinessDay]: ...

    def ensure_active_day(
        self,
        target_day: BusinessDay,
        *,
        now: datetime,
        scope: RunScope,
    ) -> DailyTransitionOutcome: ...

    def archive_for(self, day: BusinessDay) -> ArchiveProjection | None: ...


class HomeMaintenanceRunner(Protocol):
    """Home task operations used by the facade."""

    def pending_counts(self) -> tuple[int, int]: ...

    def run(
        self,
        *,
        business_day: BusinessDay,
        scope: RunScope,
        request_id: str,
    ) -> MaintenanceTaskOutcome: ...


class MemoryMaintenanceRunner(Protocol):
    """Memory task operations used by the facade."""

    def recover(self) -> None: ...

    def eligible(
        self,
        day: BusinessDay,
        *,
        archive: ArchiveProjection | None,
        if_absent: bool,
    ) -> bool: ...

    def run(
        self,
        *,
        business_day: BusinessDay,
        target_day: BusinessDay,
        archive: ArchiveProjection | None,
        scope: RunScope,
        request_id: str,
    ) -> MaintenanceTaskOutcome: ...


class MaintenanceEngine:
    """Discover and execute maintenance through one serial, non-interactive path."""

    def __init__(
        self,
        *,
        archive: ArchiveMaintenance,
        home: HomeMaintenanceRunner,
        memory: MemoryMaintenanceRunner,
        availability_store: MaintenanceAvailabilityStore,
        clock: BusinessClock,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._archive = archive
        self._home = home
        self._memory = memory
        self._availability_store = availability_store
        self._clock = clock
        self._observations = observations or NullObservationEmitter()
        self._lock = RLock()

    def active_day_lease(self) -> AbstractContextManager[BusinessDay]:
        return self._archive.active_day_lease()

    def preflight(self, *, scope: RunScope | None = None) -> DailyTransitionOutcome:
        """Recover rollover and persist the unique availability projection."""

        run_scope = scope or RunScope()
        with self._lock:
            self._memory_engine_recover()
            now = self._clock.now()
            business_day = BusinessDay(now.date())
            transition = self._archive.ensure_active_day(
                business_day,
                now=now,
                scope=run_scope,
            )
            self._reconcile_availability(transition, scope=run_scope)
            return transition

    def availability(self) -> MaintenanceAvailability:
        """Read the persisted prompt sheet without rediscovering owner facts."""

        # The store is written with atomic replacement, so this read must
        # not queue behind the engine lock: a long Maintenance run would
        # otherwise block the Endpoint availability endpoint for minutes.
        return self._availability_store.require()

    def run(
        self,
        request: MaintenanceRequest,
        *,
        scope: RunScope | None = None,
    ) -> MaintenanceOutcome:
        """Run manual and scheduled requests through the exact same workflow."""

        run_scope = scope or RunScope()
        with self._lock:
            transition = self.preflight(scope=run_scope)
            business_day = transition.active_day
            availability = self.availability()
            self._emit(
                "maintenance.started",
                "Maintenance started.",
                {"request": request.to_json()},
                scope=run_scope,
            )
            outcomes: list[MaintenanceTaskOutcome] = []
            outcomes.extend(
                self._archive_outcome(archive)
                for archive in transition.archives
            )

            if request.scope in {MaintenanceScope.DAILY, MaintenanceScope.HOME}:
                outcomes.append(
                    self._run_task(
                        MaintenanceTaskKind.HOME,
                        lambda: self._home.run(
                            business_day=business_day,
                            scope=run_scope,
                            request_id=request.request_id,
                        ),
                    )
                )

            if request.scope in {MaintenanceScope.DAILY, MaintenanceScope.MEMORY}:
                targets = self._memory_targets(
                    request,
                    availability,
                    business_day=business_day,
                )
                if not targets:
                    target_day = (
                        _previous_day(business_day)
                        if request.scope is MaintenanceScope.DAILY
                        else request.target_day
                    )
                    outcomes.append(
                        MaintenanceTaskOutcome(
                            kind=MaintenanceTaskKind.MEMORY,
                            status=MaintenanceTaskStatus.SKIPPED,
                            target_day=target_day,
                            reason=(
                                "previous_day_not_pending"
                                if request.scope is MaintenanceScope.DAILY
                                else "no_eligible_closed_day"
                            ),
                        )
                    )
                for target in targets:
                    outcomes.append(
                        self._run_task(
                            MaintenanceTaskKind.MEMORY,
                            lambda target=target: self._memory.run(
                                business_day=business_day,
                                target_day=target,
                                archive=self._archive.archive_for(target),
                                scope=run_scope,
                                request_id=request.request_id,
                            ),
                            target_day=target,
                        )
                    )

            self._reconcile_availability(
                DailyTransitionOutcome(active_day=business_day),
                scope=run_scope,
            )
            outcome = MaintenanceOutcome(
                request_id=request.request_id,
                business_day=business_day,
                status=_aggregate_status(tuple(outcomes)),
                tasks=tuple(outcomes),
            )
            self._emit(
                "maintenance.completed",
                f"Maintenance finished with {outcome.status.value}.",
                outcome.to_json(),
                scope=run_scope,
            )
            return outcome

    def _reconcile_availability(
        self,
        transition: DailyTransitionOutcome,
        *,
        scope: RunScope,
    ) -> MaintenanceAvailability:
        try:
            return self._refresh_availability(transition, scope=scope)
        except (
            AgentHomeIOError,
            AgentHomeInvariantError,
            MemoryIOError,
            MemoryInvariantError,
            SessionIOError,
            SessionInvariantError,
            WorkspaceIOError,
            WorkspaceInvariantError,
        ) as exc:
            raise MaintenanceInvariantError(
                f"Maintenance availability refresh failed: {type(exc).__name__}"
            ) from exc

    def _refresh_availability(
        self,
        transition: DailyTransitionOutcome,
        *,
        scope: RunScope,
    ) -> MaintenanceAvailability:
        previous = self._availability_store.load()
        pending = set(previous.memory_days if previous is not None else ())
        for day in tuple(pending):
            if day >= transition.active_day:
                raise MaintenanceInvariantError(
                    "Maintenance availability contains an open Business Day"
                )
            archive = self._archive.archive_for(day)
            if archive is None:
                raise MaintenanceInvariantError(
                    f"Maintenance availability references a missing archive: {day}"
                )
            if not self._memory.eligible(day, archive=archive, if_absent=True):
                pending.remove(day)

        for transitioned_archive in transition.archives:
            archive = self._archive.archive_for(transitioned_archive.day)
            if archive is None:
                raise MaintenanceInvariantError(
                    "Daily transition archive is absent from the authoritative catalog"
                )
            if archive.root != transitioned_archive.root:
                raise MaintenanceInvariantError(
                    "Daily transition archive identity does not match its projection"
                )
            if self._memory.eligible(
                transitioned_archive.day,
                archive=archive,
                if_absent=True,
            ):
                pending.add(transitioned_archive.day)
            else:
                pending.discard(transitioned_archive.day)

        home_change_count, home_skill_memory_count = self._home.pending_counts()
        availability = MaintenanceAvailability(
            checked_day=transition.active_day,
            home_change_count=home_change_count,
            home_skill_memory_count=home_skill_memory_count,
            memory_days=tuple(pending),
        )
        self._availability_store.save(availability)
        if previous != availability:
            self._emit(
                "maintenance.availability.changed",
                "Maintenance availability changed.",
                availability.to_json(),
                scope=scope,
            )
        return availability

    def _memory_targets(
        self,
        request: MaintenanceRequest,
        availability: MaintenanceAvailability,
        *,
        business_day: BusinessDay,
    ) -> tuple[BusinessDay, ...]:
        if request.scope is MaintenanceScope.DAILY:
            target_day = _previous_day(business_day)
            return (target_day,) if target_day in availability.memory_days else ()

        target_day = request.target_day
        if target_day is None:
            raise MaintenanceInvariantError(
                "Memory Maintenance request has no target day"
            )
        archive = self._archive.archive_for(target_day)
        return (
            (target_day,)
            if self._memory.eligible(
                target_day,
                archive=archive,
                if_absent=False,
            )
            else ()
        )

    def _memory_engine_recover(self) -> None:
        self._memory.recover()

    @staticmethod
    def _archive_outcome(
        archive: ArchiveProjection,
    ) -> MaintenanceTaskOutcome:
        return MaintenanceTaskOutcome(
            kind=MaintenanceTaskKind.ARCHIVE,
            status=MaintenanceTaskStatus.COMPLETED,
            target_day=archive.day,
        )

    @staticmethod
    def _run_task(
        kind: MaintenanceTaskKind,
        run: Callable[[], MaintenanceTaskOutcome],
        *,
        target_day: BusinessDay | None = None,
    ) -> MaintenanceTaskOutcome:
        try:
            return run()
        except (
            MaintenanceTaskExecutionError,
            AgentHomeIOError,
            MemoryIOError,
            SessionIOError,
            WorkspaceIOError,
        ) as exc:
            cause = exc.__cause__
            return MaintenanceTaskOutcome(
                kind=kind,
                status=MaintenanceTaskStatus.FAILED,
                target_day=target_day,
                reason="task_failed",
                details={
                    "error_type": (
                        type(cause).__name__
                        if cause is not None
                        else type(exc).__name__
                    )
                },
            )

    def _emit(
        self,
        name: str,
        message: str,
        payload: JsonObject,
        *,
        scope: RunScope,
    ) -> None:
        if not observation_enabled(self._observations, ObservationLevel.NORMAL):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name=name,
                level=ObservationLevel.NORMAL,
                source="maintenance.engine",
                scope=scope,
                message=message,
                payload=payload,
            ),
        )


def _aggregate_status(
    tasks: tuple[MaintenanceTaskOutcome, ...],
) -> MaintenanceStatus:
    statuses = tuple(task.status for task in tasks)
    if not statuses or all(status is MaintenanceTaskStatus.SKIPPED for status in statuses):
        return MaintenanceStatus.SKIPPED
    failed = sum(status is MaintenanceTaskStatus.FAILED for status in statuses)
    if failed == len(statuses):
        return MaintenanceStatus.FAILED
    if failed:
        return MaintenanceStatus.PARTIAL
    return MaintenanceStatus.COMPLETED


def _previous_day(day: BusinessDay) -> BusinessDay:
    return BusinessDay(day.value - timedelta(days=1))
