"""Single orchestration facade for deterministic and Turn-based maintenance."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from threading import RLock
from typing import Protocol

from tinysoul.infra.json import JsonObject
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunLevel,
    RunScope,
    emit_observation,
    observation_enabled,
)

from .archive import ArchiveProjection, DailyTransitionOutcome
from .day import BusinessClock, BusinessDay
from .errors import MaintenanceInvariantError
from .models import (
    MaintenanceAvailability,
    MaintenanceOutcome,
    MaintenancePlan,
    MaintenanceRequest,
    MaintenanceScope,
    MaintenanceStatus,
    MaintenanceTaskKind,
    MaintenanceTaskOutcome,
    MaintenanceTaskPlan,
    MaintenanceTaskStatus,
)
from .schedule import missed_memory_days


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

    def closed_days(self) -> tuple[BusinessDay, ...]: ...

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

    def eligible(
        self,
        day: BusinessDay,
        *,
        archive: ArchiveProjection | None,
        rebuild: bool,
    ) -> bool: ...

    def run(
        self,
        *,
        business_day: BusinessDay,
        target_day: BusinessDay,
        archive: ArchiveProjection | None,
        rebuild: bool,
        scope: RunScope,
        request_id: str,
    ) -> MaintenanceTaskOutcome: ...


class MaintenanceEngine:
    """Plan and execute all maintenance through one serial, non-interactive path."""

    def __init__(
        self,
        *,
        archive: ArchiveMaintenance,
        home: HomeMaintenanceRunner,
        memory: MemoryMaintenanceRunner,
        clock: BusinessClock,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._archive = archive
        self._home = home
        self._memory = memory
        self._clock = clock
        self._observations = observations or NullObservationEmitter()
        self._lock = RLock()

    def active_day_lease(self) -> AbstractContextManager[BusinessDay]:
        return self._archive.active_day_lease()

    def preflight(self, *, scope: RunScope | None = None) -> DailyTransitionOutcome:
        """Recover or apply rollover before any Program request uses daily state."""

        now = self._clock.now()
        business_day = BusinessDay(now.date())
        return self._archive.ensure_active_day(
            business_day,
            now=now,
            scope=(scope or RunScope()).push(RunLevel.MODULE, "archive"),
        )

    def availability(self, business_day: BusinessDay) -> MaintenanceAvailability:
        home_change_count, home_skill_memory_count = self._home.pending_counts()
        memory_days = missed_memory_days(
            (day for day in self._archive.closed_days() if day < business_day),
            eligible=lambda day: self._memory.eligible(
                day,
                archive=self._archive.archive_for(day),
                rebuild=False,
            ),
        )
        return MaintenanceAvailability(
            home_change_count=home_change_count,
            home_skill_memory_count=home_skill_memory_count,
            memory_days=memory_days,
        )

    def plan(
        self,
        request: MaintenanceRequest,
        *,
        transition: DailyTransitionOutcome,
    ) -> MaintenancePlan:
        business_day = transition.active_day
        availability = self.availability(business_day)
        tasks: list[MaintenanceTaskPlan] = []
        if transition.archive_path is not None:
            tasks.append(
                MaintenanceTaskPlan(
                    kind=MaintenanceTaskKind.ARCHIVE,
                    eligible=True,
                    target_day=self._archived_day(transition),
                )
            )
        if request.scope in {MaintenanceScope.DAILY, MaintenanceScope.HOME}:
            tasks.append(
                MaintenanceTaskPlan(
                    kind=MaintenanceTaskKind.HOME,
                    eligible=availability.home_pending,
                    reason="" if availability.home_pending else "no_home_differences",
                )
            )
        if request.scope in {MaintenanceScope.DAILY, MaintenanceScope.MEMORY}:
            memory_days = self._memory_targets(request, availability)
            tasks.append(
                MaintenanceTaskPlan(
                    kind=MaintenanceTaskKind.MEMORY,
                    eligible=bool(memory_days),
                    target_day=(memory_days[0] if len(memory_days) == 1 else None),
                    reason=("" if memory_days else "no_eligible_closed_day"),
                )
            )
        return MaintenancePlan(
            request=request,
            business_day=business_day,
            tasks=tuple(tasks),
        )

    def run(
        self,
        request: MaintenanceRequest,
        *,
        scope: RunScope | None = None,
    ) -> MaintenanceOutcome:
        """Run manual and scheduled requests through the exact same workflow."""

        run_scope = scope or RunScope().push(RunLevel.PROGRAM, "program")
        with self._lock:
            transition = self.preflight(scope=run_scope)
            plan = self.plan(request, transition=transition)
            self._emit(
                "maintenance.started",
                "Maintenance started.",
                {"request": request.to_json()},
                scope=run_scope,
            )
            outcomes: list[MaintenanceTaskOutcome] = []
            if transition.archive_path is not None:
                outcomes.append(self._archive_outcome(transition))

            if request.scope in {MaintenanceScope.DAILY, MaintenanceScope.HOME}:
                outcomes.append(
                    self._run_task(
                        MaintenanceTaskKind.HOME,
                        lambda: self._home.run(
                            business_day=plan.business_day,
                            scope=run_scope.push(RunLevel.MODULE, "maintenance.home"),
                            request_id=request.request_id,
                        ),
                    )
                )

            if request.scope in {MaintenanceScope.DAILY, MaintenanceScope.MEMORY}:
                availability = self.availability(plan.business_day)
                targets = self._memory_targets(request, availability)
                if not targets:
                    outcomes.append(
                        MaintenanceTaskOutcome(
                            kind=MaintenanceTaskKind.MEMORY,
                            status=MaintenanceTaskStatus.SKIPPED,
                            target_day=request.target_day,
                            reason="no_eligible_closed_day",
                        )
                    )
                for target in targets:
                    outcomes.append(
                        self._run_task(
                            MaintenanceTaskKind.MEMORY,
                            lambda target=target: self._memory.run(
                                business_day=plan.business_day,
                                target_day=target,
                                archive=self._archive.archive_for(target),
                                rebuild=request.rebuild_memory,
                                scope=run_scope.push(
                                    RunLevel.MODULE,
                                    "maintenance.memory",
                                ),
                                request_id=request.request_id,
                            ),
                            target_day=target,
                        )
                    )

            outcome = MaintenanceOutcome(
                request_id=request.request_id,
                business_day=plan.business_day,
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

    def _memory_targets(
        self,
        request: MaintenanceRequest,
        availability: MaintenanceAvailability,
    ) -> tuple[BusinessDay, ...]:
        if request.target_day is not None:
            archive = self._archive.archive_for(request.target_day)
            return (
                (request.target_day,)
                if self._memory.eligible(
                    request.target_day,
                    archive=archive,
                    rebuild=request.rebuild_memory,
                )
                else ()
            )
        return availability.memory_days

    def _archive_outcome(
        self,
        transition: DailyTransitionOutcome,
    ) -> MaintenanceTaskOutcome:
        return MaintenanceTaskOutcome(
            kind=MaintenanceTaskKind.ARCHIVE,
            status=MaintenanceTaskStatus.COMPLETED,
            target_day=self._archived_day(transition),
            details={"resumed": transition.resumed},
        )

    def _archived_day(self, transition: DailyTransitionOutcome) -> BusinessDay:
        assert transition.archive_path is not None
        target = transition.archive_path.resolve()
        matches = tuple(
            day
            for day in self._archive.closed_days()
            if (projection := self._archive.archive_for(day)) is not None
            and projection.root == target
        )
        if len(matches) != 1:
            raise MaintenanceInvariantError(
                "Daily transition archive is absent from the authoritative catalog"
            )
        return matches[0]

    def _run_task(
        self,
        kind: MaintenanceTaskKind,
        run: Callable[[], MaintenanceTaskOutcome],
        *,
        target_day: BusinessDay | None = None,
    ) -> MaintenanceTaskOutcome:
        try:
            return run()
        except Exception as exc:
            return MaintenanceTaskOutcome(
                kind=kind,
                status=MaintenanceTaskStatus.FAILED,
                target_day=target_day,
                reason="task_failed",
                details={"error_type": type(exc).__name__},
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
