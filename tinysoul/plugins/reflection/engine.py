"""Single orchestration facade for deterministic and Turn-based reflection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol
from tinysoul.infra.concurrency import JoinedOperations

from tinysoul.plugins.home import AgentHomeIOError, AgentHomeInvariantError
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop.interaction.inbox import TurnInbox
from tinysoul.kernel.loop.turn import TurnExecutionCancelled
from .models import ReflectionExecutionCancelled
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
from .errors import (
    ReflectionContractError,
    ReflectionInvariantError,
    ReflectionTaskExecutionError,
)
from .models import (
    ReflectionAvailability,
    ReflectionOutcome,
    ReflectionRequest,
    ReflectionScope,
    ReflectionStatus,
    ReflectionTaskKind,
    ReflectionTaskOutcome,
    ReflectionTaskStatus,
)


class ArchiveReader(Protocol):
    """Read-only archive discovery; Reflection cannot perform day transitions."""

    def archive_for(self, day: CalendarDay) -> ArchiveProjection | None: ...

    def archived_days(
        self, *, before: CalendarDay | None = None, limit: int = 64
    ) -> tuple[CalendarDay, ...]: ...


class HomeReflectionRunner(Protocol):
    """Home task operations used by the facade."""

    def pending_counts(self) -> tuple[int, int]: ...

    async def run(
        self,
        *,
        active_day: CalendarDay,
        scope: RunScope,
        request_id: str,
        inbox: TurnInbox | None = None,
        instructions: str = "",
    ) -> ReflectionTaskOutcome: ...


class MemoryReflectionRunner(Protocol):
    """Memory task operations used by the facade."""

    def eligible(
        self,
        day: CalendarDay,
        *,
        archive: ArchiveProjection | None,
    ) -> bool: ...

    def daily_days(
        self, *, before: CalendarDay | None = None, limit: int = 64
    ) -> tuple[CalendarDay, ...]: ...

    def has_daily(self, day: CalendarDay) -> bool: ...

    async def run(
        self,
        *,
        active_day: CalendarDay,
        target_day: CalendarDay,
        archive: ArchiveProjection | None,
        scope: RunScope,
        request_id: str,
        inbox: TurnInbox | None = None,
        instructions: str = "",
    ) -> ReflectionTaskOutcome: ...


class ReflectionEngine:
    """Discover and execute reflection through one serial, non-interactive path."""

    def __init__(
        self,
        *,
        archive: ArchiveReader,
        home: HomeReflectionRunner,
        memory: MemoryReflectionRunner,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._archive = archive
        self._home = home
        self._memory = memory
        self._availability: ReflectionAvailability | None = None
        self._observations = observations or NullObservationEmitter()
        self._run_lock = asyncio.Lock()

    def availability(
        self, *, before: CalendarDay | None = None
    ) -> ReflectionAvailability:
        """Return the last owner-derived projection for this process generation."""

        if before is not None and not isinstance(before, CalendarDay):
            raise ReflectionContractError(
                "Reflection date continuation must be a CalendarDay"
            )
        if self._availability is None:
            raise ReflectionInvariantError(
                "Reflection availability has not been prepared for this Agent generation"
            )
        if before is None:
            return self._availability
        return self._project_availability(self._availability.checked_day, before=before)

    async def run(
        self,
        request: ReflectionRequest,
        *,
        active_day: CalendarDay,
        scope: RunScope | None = None,
        inbox: TurnInbox | None = None,
    ) -> ReflectionOutcome:
        """Run manual and scheduled requests through the exact same workflow."""

        run_scope = scope or RunScope()
        async with self._run_lock:
            operations = JoinedOperations()
            await operations.run(
                lambda: self.refresh_availability(
                    DailyTransitionOutcome(active_day),
                    scope=run_scope,
                )
            )
            operations.check_cancelled()
            self._emit(
                "reflection.started",
                "Reflection started.",
                {
                    "active_day": str(active_day),
                    "request": request.to_json(),
                },
                scope=run_scope,
            )
            outcomes: list[ReflectionTaskOutcome] = []

            def completed() -> ReflectionOutcome:
                return ReflectionOutcome(
                    request_id=request.request_id,
                    active_day=active_day,
                    status=_aggregate_status(tuple(outcomes)),
                    tasks=tuple(outcomes),
                )

            async def run_task(
                kind: ReflectionTaskKind,
                run: Callable[[], Awaitable[ReflectionTaskOutcome]],
                *,
                target_day: CalendarDay | None = None,
            ) -> ReflectionTaskOutcome:
                try:
                    return await self._run_task(kind, run, target_day=target_day)
                except TurnExecutionCancelled as exc:
                    outcomes.append(
                        ReflectionTaskOutcome.from_turn(
                            kind,
                            exc.outcome,
                            target_day=target_day,
                        )
                    )
                    raise ReflectionExecutionCancelled(completed()) from exc
                except asyncio.CancelledError as exc:
                    outcomes.append(
                        ReflectionTaskOutcome(
                            kind,
                            ReflectionTaskStatus.CANCELLED,
                            target_day=target_day,
                        )
                    )
                    raise ReflectionExecutionCancelled(completed()) from exc

            if request.scope in {ReflectionScope.DAILY, ReflectionScope.HOME}:
                outcomes.append(
                    (
                        await run_task(
                            ReflectionTaskKind.HOME,
                            lambda: self._home.run(
                                active_day=active_day,
                                scope=run_scope,
                                request_id=request.request_id,
                                inbox=inbox,
                                instructions=request.instructions,
                            ),
                        )
                    )
                )

            if request.scope in {ReflectionScope.DAILY, ReflectionScope.MEMORY}:
                targets = await operations.run(
                    lambda: self._memory_targets(
                        request,
                        active_day=active_day,
                    )
                )
                operations.check_cancelled()
                if not targets:
                    target_day = (
                        _previous_day(active_day)
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
                                else "target_sources_empty"
                            ),
                        )
                    )
                for target in targets:
                    archive = await operations.run(lambda: self._archive_for(target))
                    operations.check_cancelled()
                    outcomes.append(
                        (
                            await run_task(
                                ReflectionTaskKind.MEMORY,
                                lambda target=target: self._memory.run(
                                    active_day=active_day,
                                    target_day=target,
                                    archive=archive,
                                    scope=run_scope,
                                    request_id=request.request_id,
                                    inbox=inbox,
                                    instructions=request.instructions,
                                ),
                                target_day=target,
                            )
                        )
                    )

            await operations.run(
                lambda: self.refresh_availability(
                    DailyTransitionOutcome(active_day=active_day),
                    scope=run_scope,
                )
            )
            outcome = completed()
            self._emit(
                "reflection.completed",
                f"Reflection finished with {outcome.status.value}.",
                outcome.to_json(),
                scope=run_scope,
            )
            if operations.cancelled:
                raise ReflectionExecutionCancelled(outcome)
            return outcome

    def refresh_availability(
        self,
        transition: DailyTransitionOutcome,
        *,
        scope: RunScope,
    ) -> ReflectionAvailability:
        availability = self._project_availability(transition.active_day)
        previous = self._availability
        self._availability = availability
        if previous != availability:
            self._emit(
                "reflection.availability.changed",
                "Reflection availability changed.",
                availability.to_json(),
                scope=scope,
            )
        return availability

    def _project_availability(
        self, active_day: CalendarDay, *, before: CalendarDay | None = None
    ) -> ReflectionAvailability:
        try:
            return self._load_availability(active_day, before=before)
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

    def _load_availability(
        self, active_day: CalendarDay, *, before: CalendarDay | None = None
    ) -> ReflectionAvailability:
        limit = 64
        end = CalendarDay(active_day.value + timedelta(days=1))
        upper_bound = min(before, end) if before is not None else end
        pending: set[CalendarDay] = set()
        try:
            candidates = set(
                self._archive.archived_days(before=upper_bound, limit=limit + 1)
            )
        except ArchiveError as exc:
            raise RuntimeArchiveBridge().from_archive_error(exc) from exc
        candidates.update(self._memory.daily_days(before=upper_bound, limit=limit + 1))
        if before is None or active_day < before:
            candidates.add(active_day)
        ordered = sorted((day for day in candidates if day <= active_day), reverse=True)
        page = ordered[:limit]
        for day in page:
            archive = self._archive_for(day)
            if self._memory.eligible(day, archive=archive):
                pending.add(day)

        home_change_count, home_skill_memory_count = self._home.pending_counts()
        return ReflectionAvailability(
            checked_day=active_day,
            home_change_count=home_change_count,
            home_skill_memory_count=home_skill_memory_count,
            memory_days=tuple(pending),
            missing_daily_days=tuple(
                day for day in pending if not self._memory.has_daily(day)
            ),
            next_before=page[-1] if len(ordered) > limit else None,
            scanned_days=len(page),
        )

    def _archive_for(self, day: CalendarDay) -> ArchiveProjection | None:
        try:
            return self._archive.archive_for(day)
        except ArchiveError as exc:
            raise RuntimeArchiveBridge().from_archive_error(exc) from exc

    def _memory_targets(
        self,
        request: ReflectionRequest,
        *,
        active_day: CalendarDay,
    ) -> tuple[CalendarDay, ...]:
        target_day = (
            _previous_day(active_day)
            if request.scope is ReflectionScope.DAILY
            else request.target_day
        )
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
                source="reflection.engine",
                scope=scope,
                message=message,
                payload=payload,
            ),
        )


def _aggregate_status(
    tasks: tuple[ReflectionTaskOutcome, ...],
) -> ReflectionStatus:
    statuses = tuple(task.status for task in tasks)
    if not statuses or all(
        status is ReflectionTaskStatus.SKIPPED for status in statuses
    ):
        return ReflectionStatus.SKIPPED
    failed = sum(status is ReflectionTaskStatus.FAILED for status in statuses)
    if failed == len(statuses):
        return ReflectionStatus.FAILED
    if failed:
        return ReflectionStatus.PARTIAL
    for status in (
        ReflectionTaskStatus.CANCELLED,
        ReflectionTaskStatus.AWAITING_USER,
        ReflectionTaskStatus.STOPPED,
        ReflectionTaskStatus.EXHAUSTED,
    ):
        if status in statuses:
            return ReflectionStatus(status.value)
    return ReflectionStatus.COMPLETED


def _previous_day(day: CalendarDay) -> CalendarDay:
    return CalendarDay(day.value - timedelta(days=1))
