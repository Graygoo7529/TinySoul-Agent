from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tinysoul.infra.time import CalendarDay
from tinysoul.plugins.memory import MemoryIOError
from tinysoul.plugins.archive import ArchiveProjection
from tinysoul.plugins.archive import DailyTransitionOutcome
from tinysoul.plugins.reflection import (
    ReflectionAvailability,
    ReflectionContractError,
    ReflectionEngine,
    ReflectionInvariantError,
    ReflectionRequest,
    ReflectionScope,
    ReflectionTaskKind,
    ReflectionTaskOutcome,
    ReflectionTaskStatus,
    ReflectionTrigger,
)
from tinysoul.runtime import ObservationEvent, ObservationLevel, RunScope
from tinysoul.kernel.loop.turn import TurnOutcome, TurnExecutionCancelled
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.plugins.reflection.models import ReflectionExecutionCancelled

TODAY = CalendarDay.parse("2026-08-03")
DAY_ONE = CalendarDay.parse("2026-08-01")
DAY_TWO = CalendarDay.parse("2026-08-02")


@pytest.mark.parametrize(
    "status", [TurnOutcomeStatus.CANCELLED, TurnOutcomeStatus.COMPLETED]
)
async def test_reflection_cancel_retains_target_and_owner_completion(
    tmp_path: Path, status: TurnOutcomeStatus
) -> None:
    turn = TurnOutcome(
        context_completion=None,
        active_day=TODAY,
        status=status,
        completion=(
            {"summary": "persisted before cancellation"}
            if status is TurnOutcomeStatus.COMPLETED
            else None
        ),
    )

    class CancelledMemory(_Memory):
        async def run(self, **kwargs):
            raise TurnExecutionCancelled(turn)

    engine = _engine(
        tmp_path, archive=_Archive(tmp_path, (DAY_TWO,)), memory=CancelledMemory()
    )
    request = ReflectionRequest(
        scope=ReflectionScope.MEMORY,
        trigger=ReflectionTrigger.MANUAL,
        target_day=DAY_TWO,
    )
    with pytest.raises(ReflectionExecutionCancelled) as cancelled:
        await engine.run(request, active_day=TODAY)
    outcome = cancelled.value.outcome
    assert outcome.request_id == request.request_id and outcome.active_day == TODAY
    task = outcome.tasks[0]
    assert task.kind is ReflectionTaskKind.MEMORY and task.target_day == DAY_TWO
    assert task.turn_outcome is turn and task.status.value == status.value


def test_preflight_rebuilds_candidates_from_owner_catalogs(tmp_path: Path) -> None:
    archive = _Archive(tmp_path, (DAY_ONE, DAY_TWO), transition_day=DAY_TWO)
    memory = _Memory()
    engine = _engine(tmp_path, archive=archive, memory=memory)

    engine.refresh_availability(
        archive.ensure_active_day(TODAY, now=_Clock().now()), scope=RunScope()
    )

    availability = engine.availability()
    assert availability.checked_day == TODAY
    assert availability.memory_days == (DAY_ONE, DAY_TWO)
    assert set(archive.requested_days) == {DAY_ONE, DAY_TWO, TODAY}


def test_candidate_pages_are_bounded_and_reconstructible(tmp_path: Path) -> None:
    days = tuple(
        CalendarDay(TODAY.value - timedelta(days=index)) for index in range(1, 140)
    )
    archive = _Archive(tmp_path, days)
    memory = _Memory(existing={days[0]})
    engine = _engine(tmp_path, archive=archive, memory=memory)
    page = engine.refresh_availability(DailyTransitionOutcome(TODAY), scope=RunScope())
    found: set[CalendarDay] = set()
    while True:
        assert page.scanned_days <= 64
        assert not found.intersection(page.memory_days)
        found.update(page.memory_days)
        if page.next_before is None:
            break
        page = engine.availability(before=page.next_before)
    assert found == set(days)
    assert days[0] not in engine.availability().missing_daily_days
    restarted = _engine(tmp_path, archive=archive, memory=memory)
    assert (
        restarted.refresh_availability(DailyTransitionOutcome(TODAY), scope=RunScope())
        == engine.availability()
    )


def test_preflight_projects_home_and_all_memory_backlog(tmp_path: Path) -> None:
    archive = _Archive(tmp_path, (DAY_ONE,))
    engine = _engine(
        tmp_path,
        archive=archive,
        home=_Home(pending=True),
    )

    engine.refresh_availability(
        archive.ensure_active_day(TODAY, now=_Clock().now()), scope=RunScope()
    )

    availability = engine.availability()
    assert availability.home_pending
    assert availability.home_change_count == 1
    assert availability.memory_days == (DAY_ONE,)


@pytest.mark.parametrize(
    "trigger",
    (ReflectionTrigger.SCHEDULED,),
)
async def test_daily_reflection_processes_only_previous_day_and_retains_backlog(
    tmp_path: Path,
    trigger: ReflectionTrigger,
) -> None:
    archive = _Archive(tmp_path, (DAY_ONE, DAY_TWO))
    home = _Home(pending=True)
    memory = _Memory()
    engine = _engine(
        tmp_path,
        archive=archive,
        home=home,
        memory=memory,
    )

    outcome = await engine.run(
        ReflectionRequest(
            scope=ReflectionScope.DAILY,
            trigger=trigger,
        ),
        active_day=TODAY,
    )

    assert [task.kind for task in outcome.tasks] == [
        ReflectionTaskKind.HOME,
        ReflectionTaskKind.MEMORY,
    ]
    assert memory.ran == [DAY_TWO]
    assert home.runs == 1
    assert engine.availability().memory_days == (DAY_ONE, DAY_TWO)
    assert engine.availability().missing_daily_days == (DAY_ONE,)
    assert not engine.availability().home_pending


async def test_daily_reflection_skips_absent_previous_day_and_retains_backlog(
    tmp_path: Path,
) -> None:
    archive = _Archive(tmp_path, (DAY_ONE,))
    memory = _Memory()
    engine = _engine(tmp_path, archive=archive, memory=memory)

    outcome = await engine.run(
        ReflectionRequest(
            scope=ReflectionScope.DAILY,
            trigger=ReflectionTrigger.SCHEDULED,
        ),
        active_day=TODAY,
    )

    memory_outcome = outcome.tasks[-1]
    assert memory_outcome.kind is ReflectionTaskKind.MEMORY
    assert memory_outcome.status is ReflectionTaskStatus.SKIPPED
    assert memory_outcome.target_day == DAY_TWO
    assert memory_outcome.reason == "previous_day_not_pending"
    assert memory.ran == []
    assert engine.availability().memory_days == (DAY_ONE,)


async def test_failed_memory_day_remains_available_across_restart(
    tmp_path: Path,
) -> None:
    archive = _Archive(tmp_path, (DAY_ONE,))
    memory = _Memory(fail_days={DAY_ONE})
    engine = _engine(tmp_path, archive=archive, memory=memory)

    outcome = await engine.run(
        ReflectionRequest(
            scope=ReflectionScope.MEMORY,
            trigger=ReflectionTrigger.MANUAL,
            target_day=DAY_ONE,
        ),
        active_day=TODAY,
    )

    assert outcome.tasks[0].status is ReflectionTaskStatus.FAILED
    assert engine.availability().memory_days == (DAY_ONE,)
    restarted = _engine(tmp_path, archive=archive, memory=memory)
    restarted.refresh_availability(
        archive.ensure_active_day(TODAY, now=_Clock().now()), scope=RunScope()
    )
    assert restarted.availability().memory_days == (DAY_ONE,)


def test_memory_request_requires_explicit_target_day() -> None:
    with pytest.raises(ReflectionContractError, match="explicit target day"):
        ReflectionRequest(
            scope=ReflectionScope.MEMORY,
            trigger=ReflectionTrigger.MANUAL,
        )


async def test_manual_and_scheduled_home_requests_use_the_same_task_path(
    tmp_path: Path,
) -> None:
    outcomes = []
    homes = []
    for index, trigger in enumerate(
        (ReflectionTrigger.MANUAL, ReflectionTrigger.SCHEDULED)
    ):
        home = _Home(pending=True)
        homes.append(home)
        engine = _engine(
            tmp_path / str(index),
            archive=_Archive(tmp_path / str(index), ()),
            home=home,
        )
        outcomes.append(
            await engine.run(
                ReflectionRequest(
                    scope=ReflectionScope.HOME,
                    trigger=trigger,
                ),
                active_day=TODAY,
            )
        )

    assert [home.runs for home in homes] == [1, 1]
    assert [item.tasks[0].status for item in outcomes] == [
        ReflectionTaskStatus.COMPLETED,
        ReflectionTaskStatus.COMPLETED,
    ]


async def test_explicit_memory_reflection_does_not_require_pending_entry(
    tmp_path: Path,
) -> None:
    memory = _Memory(existing={DAY_ONE})
    engine = _engine(
        tmp_path,
        archive=_Archive(tmp_path, (DAY_ONE, DAY_TWO)),
        memory=memory,
    )

    await engine.run(
        ReflectionRequest(
            scope=ReflectionScope.MEMORY,
            trigger=ReflectionTrigger.MANUAL,
            target_day=DAY_ONE,
        ),
        active_day=TODAY,
    )

    assert memory.ran == [DAY_ONE]
    assert engine.availability().memory_days == (DAY_ONE, DAY_TWO)
    assert engine.availability().missing_daily_days == (DAY_TWO,)


async def test_started_observation_distinguishes_execution_day_from_memory_target(
    tmp_path: Path,
) -> None:
    observations = _RecordingObservations()
    engine = _engine(
        tmp_path,
        archive=_Archive(tmp_path, (DAY_ONE,)),
        observations=observations,
    )

    await engine.run(
        ReflectionRequest(
            scope=ReflectionScope.MEMORY,
            trigger=ReflectionTrigger.MANUAL,
            target_day=DAY_ONE,
            source="endpoint",
            request_id="reflection_request",
        ),
        active_day=TODAY,
    )

    started = next(
        event for event in observations.events if event.name == "reflection.started"
    )
    assert started.payload == {
        "active_day": str(TODAY),
        "request": {
            "scope": "memory",
            "trigger": "manual",
            "source": "endpoint",
            "request_id": "reflection_request",
            "metadata": {},
            "instructions": "",
            "target_day": str(DAY_ONE),
        },
    }


def test_availability_uses_archive_owner_instead_of_transition_paths(
    tmp_path: Path,
) -> None:
    archive = _Archive(tmp_path, (DAY_ONE,), transition_day=DAY_ONE)
    archive.transition_path = (tmp_path / "unknown-archive").resolve()
    engine = _engine(tmp_path, archive=archive)

    engine.refresh_availability(
        archive.ensure_active_day(TODAY, now=_Clock().now()), scope=RunScope()
    )
    assert engine.availability().memory_days == (DAY_ONE,)


async def test_unknown_task_exception_is_not_downgraded(tmp_path: Path) -> None:
    engine = _engine(
        tmp_path,
        archive=_Archive(tmp_path, ()),
        home=_Home(unexpected_failure=True),
    )

    with pytest.raises(AttributeError, match="unexpected"):
        await engine.run(
            ReflectionRequest(
                scope=ReflectionScope.HOME,
                trigger=ReflectionTrigger.MANUAL,
            ),
            active_day=TODAY,
        )


def _engine(
    root: Path,
    *,
    archive: "_Archive",
    home: "_Home | None" = None,
    memory: "_Memory | None" = None,
    observations: "_RecordingObservations | None" = None,
) -> ReflectionEngine:
    return ReflectionEngine(
        archive=archive,
        home=home or _Home(),
        memory=memory or _Memory(),
        observations=observations,
    )


@dataclass
class _Clock:
    current: datetime = datetime(2026, 8, 3, 8, tzinfo=ZoneInfo("Asia/Shanghai"))

    def now(self) -> datetime:
        return self.current

    def today(self) -> CalendarDay:
        return CalendarDay(self.current.date())


@dataclass
class _RecordingObservations:
    events: list[ObservationEvent] = field(default_factory=list)

    def enabled(self, level: ObservationLevel) -> bool:
        del level
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)


class _Archive:
    def __init__(
        self,
        root: Path,
        days: tuple[CalendarDay, ...],
        *,
        transition_day: CalendarDay | None = None,
    ) -> None:
        self._transition_day = transition_day
        self._projections = {
            day: ArchiveProjection(
                day=day,
                root=(root / str(day)).resolve(),
                session_root=(root / str(day) / "session").resolve(),
                workspace_root=(root / str(day) / "workspace").resolve(),
            )
            for day in days
        }
        self.transition_path = (
            self._projections[transition_day].root
            if transition_day is not None
            else None
        )
        self.requested_days: list[CalendarDay] = []

    def ensure_active_day(self, target_day, *, now, scope=None):
        del now, scope
        transition_day = self._transition_day
        self._transition_day = None
        if transition_day is None:
            return DailyTransitionOutcome(active_day=target_day)
        projection = self._projections[transition_day]
        if self.transition_path != projection.root:
            assert self.transition_path is not None
            projection = ArchiveProjection(
                day=projection.day,
                root=self.transition_path,
                session_root=projection.session_root,
                workspace_root=projection.workspace_root,
            )
        return DailyTransitionOutcome(
            active_day=target_day,
            archives=(projection,),
        )

    @contextmanager
    def active_day_lease(self):
        yield TODAY

    def archived_days(self, *, before=None, limit=64):
        return tuple(
            day
            for day in sorted(self._projections, reverse=True)
            if before is None or day < before
        )[:limit]

    def archive_for(self, day):
        self.requested_days.append(day)
        return self._projections.get(day)


@dataclass
class _Home:
    pending: bool = False
    runs: int = 0
    unexpected_failure: bool = False

    def pending_counts(self) -> tuple[int, int]:
        return (1, 0) if self.pending else (0, 0)

    async def run(
        self, *, active_day, scope, request_id, inbox=None, instructions=""
    ):
        del active_day, scope, request_id
        if self.unexpected_failure:
            raise AttributeError("unexpected task bug")
        self.runs += 1
        self.pending = False
        return ReflectionTaskOutcome(
            kind=ReflectionTaskKind.HOME,
            status=ReflectionTaskStatus.COMPLETED,
        )


@dataclass
class _Memory:
    existing: set[CalendarDay] = field(default_factory=set)
    ran: list[CalendarDay] = field(default_factory=list)
    fail_days: set[CalendarDay] = field(default_factory=set)

    def recover(self) -> None:
        return None

    def daily_days(self, *, before=None, limit=64):
        return tuple(
            day
            for day in sorted(self.existing, reverse=True)
            if before is None or day < before
        )[:limit]

    def has_daily(self, day):
        return day in self.existing

    def eligible(self, day, *, archive):
        return archive is not None or day in self.existing

    async def run(
        self,
        *,
        active_day,
        target_day,
        archive,
        scope,
        request_id,
        inbox=None,
        instructions="",
    ):
        del active_day, archive, scope, request_id
        self.ran.append(target_day)
        if target_day in self.fail_days:
            raise MemoryIOError("known owner failure")
        self.existing.add(target_day)
        return ReflectionTaskOutcome(
            kind=ReflectionTaskKind.MEMORY,
            status=ReflectionTaskStatus.COMPLETED,
            target_day=target_day,
        )
