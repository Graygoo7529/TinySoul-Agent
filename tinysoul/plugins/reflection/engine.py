"""Single orchestration facade for deterministic and Turn-based maintenance."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol
from tinysoul.infra.concurrency import JoinedOperations

from tinysoul.plugins.home import AgentHomeIOError, AgentHomeInvariantError
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.inbox import TurnInbox
from tinysoul.kernel.loop.turn import TurnExecutionCancelled
from tinysoul.plugins.memory import MemoryIOError, MemoryInvariantError
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunScope,
    emit_observation,
    observation_enabled,
)
from tinysoul.plugins.session import SessionIOError, SessionInvariantError
from tinysoul.plugins.workspace import WorkspaceIOError, WorkspaceInvariantError

from tinysoul.plugins.archive import ArchiveProjection, DailyTransitionOutcome
from tinysoul.plugins.archive.errors import ArchiveError
from tinysoul.plugins.archive.runtime_bridge import RuntimeArchiveBridge
from .availability import ReflectionAvailabilityStore
from .errors import ReflectionInvariantError, ReflectionTaskExecutionError
from .models import (
    ReflectionAvailability,
    ReflectionOutcome,
    ReflectionRequest,
    ReflectionScope,
    ReflectionStatus,
    ReflectionTaskKind,
    ReflectionTaskOutcome,
    ReflectionTaskStatus,
    ReflectionTrigger,
)


class ArchiveReader(Protocol):
    """Read-only archive discovery; Reflection cannot perform day transitions."""

    def archive_for(self, day: CalendarDay) -> ArchiveProjection | None: ...


class HomeReflectionRunner(Protocol):
    """Home task operations used by the facade."""

    def pending_counts(self) -> tuple[int, int]: ...

    async def run(
        self,
        *,
        business_day: CalendarDay,
        scope: RunScope,
        request_id: str,
        inbox: TurnInbox | None = None,
    ) -> ReflectionTaskOutcome: ...


class MemoryReflectionRunner(Protocol):
    """Memory task operations used by the facade."""

    def eligible(
        self,
        day: CalendarDay,
        *,
        archive: ArchiveProjection | None,
        if_absent: bool,
    ) -> bool: ...

    async def run(
        self,
        *,
        business_day: CalendarDay,
        target_day: CalendarDay,
        archive: ArchiveProjection | None,
        scope: RunScope,
        request_id: str,
        inbox: TurnInbox | None = None,
    ) -> ReflectionTaskOutcome: ...


class ReflectionEngine:
    """Discover and execute maintenance through one serial, non-interactive path."""

    def __init__(
        self,
        *,
        archive: ArchiveReader,
        home: HomeReflectionRunner,
        memory: MemoryReflectionRunner,
        availability_store: ReflectionAvailabilityStore,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._archive = archive
        self._home = home
        self._memory = memory
        self._availability_store = availability_store
        self._observations = observations or NullObservationEmitter()
        self._run_lock = asyncio.Lock()

    def availability(self) -> ReflectionAvailability:
        """Read the persisted prompt sheet without rediscovering owner facts."""

        # The store is written with atomic replacement, so this read must
        # not queue behind the engine lock: a long Reflection run would
        # otherwise block the Endpoint availability endpoint for minutes.
        return self._availability_store.require()

    async def run(
        self,
        request: ReflectionRequest,
        *,
        business_day: CalendarDay,
        scope: RunScope | None = None,
        inbox: TurnInbox | None = None,
    ) -> ReflectionOutcome:
        """Run manual and scheduled requests through the exact same workflow."""

        run_scope = scope or RunScope()
        async with self._run_lock:
            operations = JoinedOperations()
            availability = await operations.run(lambda: self.refresh_availability(
                DailyTransitionOutcome(business_day), scope=run_scope,
            ))
            operations.check_cancelled()
            self._emit(
                "maintenance.started",
                "Reflection started.",
                {
                    "business_day": str(business_day),
                    "request": request.to_json(),
                },
                scope=run_scope,
            )
            outcomes: list[ReflectionTaskOutcome] = []

            if request.scope in {ReflectionScope.DAILY, ReflectionScope.HOME}:
                outcomes.append(
                    (await self._run_task(
                        ReflectionTaskKind.HOME,
                        lambda: self._home.run(
                            business_day=business_day,
                            scope=run_scope,
                            request_id=request.request_id,
                            inbox=inbox,
                        ),
                    ))
                )

            if request.scope in {ReflectionScope.DAILY, ReflectionScope.MEMORY}:
                targets = await operations.run(lambda: self._memory_targets(
                    request,
                    availability,
                    business_day=business_day,
                ))
                operations.check_cancelled()
                if not targets:
                    target_day = (
                        _previous_day(business_day)
                        if request.scope is ReflectionScope.DAILY
                        else request.target_day
                    )
                    outcomes.append(
                        ReflectionTaskOutcome(
                            kind=ReflectionTaskKind.MEMORY,
                            status=ReflectionTaskStatus.SKIPPED,
                            target_day=target_day,
                            reason=(
                                "previous_day_not_pending"
                                if request.scope is ReflectionScope.DAILY
                                else "no_eligible_closed_day"
                            ),
                        )
                    )
                for target in targets:
                    archive = await operations.run(lambda: self._archive_for(target))
                    operations.check_cancelled()
                    outcomes.append(
                        (await self._run_task(
                            ReflectionTaskKind.MEMORY,
                            lambda target=target: self._memory.run(
                                business_day=business_day,
                                target_day=target,
                                archive=archive,
                                scope=run_scope,
                                request_id=request.request_id,
                                inbox=inbox,
                            ),
                            target_day=target,
                        ))
                    )

            await operations.run(lambda: self.refresh_availability(
                DailyTransitionOutcome(active_day=business_day),
                scope=run_scope,
            ))
            if operations.cancelled:
                for task in reversed(outcomes):
                    if task.turn_outcome is not None:
                        raise TurnExecutionCancelled(task.turn_outcome)
                operations.check_cancelled()
            outcome = ReflectionOutcome(
                request_id=request.request_id,
                business_day=business_day,
                status=_aggregate_status(tuple(outcomes)),
                tasks=tuple(outcomes),
            )
            self._emit(
                "maintenance.completed",
                f"Reflection finished with {outcome.status.value}.",
                outcome.to_json(),
                scope=run_scope,
            )
            return outcome

    def refresh_availability(
        self,
        transition: DailyTransitionOutcome,
        *,
        scope: RunScope,
    ) -> ReflectionAvailability:
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
            raise ReflectionInvariantError(
                f"Reflection availability refresh failed: {type(exc).__name__}"
            ) from exc

    def _refresh_availability(
        self,
        transition: DailyTransitionOutcome,
        *,
        scope: RunScope,
    ) -> ReflectionAvailability:
        previous = self._availability_store.load()
        pending = set(previous.memory_days if previous is not None else ())
        for day in tuple(pending):
            if day >= transition.active_day:
                raise ReflectionInvariantError(
                    "Reflection availability contains an open Business Day"
                )
            archive = self._archive_for(day)
            if archive is None:
                raise ReflectionInvariantError(
                    f"Reflection availability references a missing archive: {day}"
                )
            if not self._memory.eligible(day, archive=archive, if_absent=True):
                pending.remove(day)

        for transitioned_archive in transition.archives:
            archive = self._archive_for(transitioned_archive.day)
            if archive is None:
                raise ReflectionInvariantError(
                    "Daily transition archive is absent from the authoritative catalog"
                )
            if archive.root != transitioned_archive.root:
                raise ReflectionInvariantError(
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
        availability = ReflectionAvailability(
            checked_day=transition.active_day,
            home_change_count=home_change_count,
            home_skill_memory_count=home_skill_memory_count,
            memory_days=tuple(pending),
        )
        self._availability_store.save(availability)
        if previous != availability:
            self._emit(
                "maintenance.availability.changed",
                "Reflection availability changed.",
                availability.to_json(),
                scope=scope,
            )
        return availability

    def _archive_for(self, day: CalendarDay) -> ArchiveProjection | None:
        try:
            return self._archive.archive_for(day)
        except ArchiveError as exc:
            raise RuntimeArchiveBridge().from_archive_error(exc) from exc

    def _memory_targets(
        self,
        request: ReflectionRequest,
        availability: ReflectionAvailability,
        *,
        business_day: CalendarDay,
    ) -> tuple[CalendarDay, ...]:
        if request.scope is ReflectionScope.DAILY:
            target_day = _previous_day(business_day)
            return (target_day,) if target_day in availability.memory_days else ()

        target_day = request.target_day
        if target_day is None:
            raise ReflectionInvariantError(
                "Memory Reflection request has no target day"
            )
        archive = self._archive_for(target_day)
        return (
            (target_day,)
            if self._memory.eligible(
                target_day,
                archive=archive,
                if_absent=request.trigger is ReflectionTrigger.SCHEDULED,
            )
            else ()
        )

    async def _run_task(
        self,
        kind: ReflectionTaskKind,
        run: Callable[[], Awaitable[ReflectionTaskOutcome]],
        *,
        target_day: CalendarDay | None = None,
    ) -> ReflectionTaskOutcome:
        try:
            return await run()
        except (
            ReflectionTaskExecutionError,
            AgentHomeIOError,
            MemoryIOError,
            SessionIOError,
            WorkspaceIOError,
        ) as exc:
            cause = exc.__cause__
            return ReflectionTaskOutcome(
                kind=kind,
                status=ReflectionTaskStatus.FAILED,
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
    tasks: tuple[ReflectionTaskOutcome, ...],
) -> ReflectionStatus:
    statuses = tuple(task.status for task in tasks)
    if not statuses or all(status is ReflectionTaskStatus.SKIPPED for status in statuses):
        return ReflectionStatus.SKIPPED
    failed = sum(status is ReflectionTaskStatus.FAILED for status in statuses)
    if failed == len(statuses):
        return ReflectionStatus.FAILED
    if failed:
        return ReflectionStatus.PARTIAL
    for status in (
        ReflectionTaskStatus.AWAITING_USER,
        ReflectionTaskStatus.STOPPED,
        ReflectionTaskStatus.EXHAUSTED,
    ):
        if status in statuses:
            return ReflectionStatus(status.value)
    return ReflectionStatus.COMPLETED


def _previous_day(day: CalendarDay) -> CalendarDay:
    return CalendarDay(day.value - timedelta(days=1))
