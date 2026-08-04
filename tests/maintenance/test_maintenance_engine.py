from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tinysoul.infra.time import BusinessDay
from tinysoul.memory import MemoryIOError
from tinysoul.maintenance import (
    ArchiveProjection,
    DailyTransitionOutcome,
    MaintenanceAvailability,
    MaintenanceAvailabilityStore,
    MaintenanceEngine,
    MaintenanceInvariantError,
    MaintenanceRequest,
    MaintenanceScope,
    MaintenanceTaskKind,
    MaintenanceTaskOutcome,
    MaintenanceTaskStatus,
    MaintenanceTrigger,
)


TODAY = BusinessDay.parse("2026-08-03")
DAY_ONE = BusinessDay.parse("2026-08-01")
DAY_TWO = BusinessDay.parse("2026-08-02")


def test_preflight_registers_only_the_new_archive_day(tmp_path: Path) -> None:
    archive = _Archive(tmp_path, (DAY_ONE, DAY_TWO), transition_day=DAY_TWO)
    memory = _Memory()
    engine, store = _engine(tmp_path, archive=archive, memory=memory)

    engine.preflight()

    availability = store.require()
    assert availability.checked_day == TODAY
    assert availability.memory_days == (DAY_TWO,)
    assert archive.requested_days == [DAY_TWO]


def test_daily_maintenance_processes_persisted_memory_days_and_clears_them(
    tmp_path: Path,
) -> None:
    archive = _Archive(tmp_path, (DAY_ONE, DAY_TWO))
    home = _Home(pending=True)
    memory = _Memory()
    engine, store = _engine(
        tmp_path,
        archive=archive,
        home=home,
        memory=memory,
    )
    store.save(
        MaintenanceAvailability(
            checked_day=TODAY,
            memory_days=(DAY_ONE, DAY_TWO),
        )
    )

    outcome = engine.run(
        MaintenanceRequest(
            scope=MaintenanceScope.DAILY,
            trigger=MaintenanceTrigger.SCHEDULED,
        )
    )

    assert [task.kind for task in outcome.tasks] == [
        MaintenanceTaskKind.HOME,
        MaintenanceTaskKind.MEMORY,
        MaintenanceTaskKind.MEMORY,
    ]
    assert memory.ran == [DAY_ONE, DAY_TWO]
    assert home.runs == 1
    assert store.require().memory_days == ()
    assert not store.require().home_pending


def test_failed_memory_day_remains_available_across_restart(tmp_path: Path) -> None:
    archive = _Archive(tmp_path, (DAY_ONE,))
    memory = _Memory(fail_days={DAY_ONE})
    engine, store = _engine(tmp_path, archive=archive, memory=memory)
    store.save(
        MaintenanceAvailability(checked_day=TODAY, memory_days=(DAY_ONE,))
    )

    outcome = engine.run(
        MaintenanceRequest(
            scope=MaintenanceScope.MEMORY,
            trigger=MaintenanceTrigger.MANUAL,
        )
    )

    assert outcome.tasks[0].status is MaintenanceTaskStatus.FAILED
    assert store.require().memory_days == (DAY_ONE,)
    restarted, _ = _engine(tmp_path, archive=archive, memory=memory)
    restarted.preflight()
    assert restarted.availability().memory_days == (DAY_ONE,)


def test_manual_and_scheduled_home_requests_use_the_same_task_path(
    tmp_path: Path,
) -> None:
    outcomes = []
    homes = []
    for index, trigger in enumerate(
        (MaintenanceTrigger.MANUAL, MaintenanceTrigger.SCHEDULED)
    ):
        home = _Home(pending=True)
        homes.append(home)
        engine, _store = _engine(
            tmp_path / str(index),
            archive=_Archive(tmp_path / str(index), ()),
            home=home,
        )
        outcomes.append(
            engine.run(
                MaintenanceRequest(
                    scope=MaintenanceScope.HOME,
                    trigger=trigger,
                )
            )
        )

    assert [home.runs for home in homes] == [1, 1]
    assert [item.tasks[0].status for item in outcomes] == [
        MaintenanceTaskStatus.COMPLETED,
        MaintenanceTaskStatus.COMPLETED,
    ]


def test_explicit_memory_rebuild_does_not_require_pending_entry(
    tmp_path: Path,
) -> None:
    memory = _Memory(existing={DAY_ONE})
    engine, store = _engine(
        tmp_path,
        archive=_Archive(tmp_path, (DAY_ONE, DAY_TWO)),
        memory=memory,
    )

    engine.run(
        MaintenanceRequest(
            scope=MaintenanceScope.MEMORY,
            trigger=MaintenanceTrigger.MANUAL,
            target_day=DAY_ONE,
            rebuild_memory=True,
        )
    )

    assert memory.ran == [DAY_ONE]
    assert store.require().memory_days == ()


def test_archive_outcome_requires_authoritative_catalog_identity(
    tmp_path: Path,
) -> None:
    archive = _Archive(tmp_path, (DAY_ONE,), transition_day=DAY_ONE)
    archive.transition_path = (tmp_path / "unknown-archive").resolve()
    engine, _store = _engine(tmp_path, archive=archive)

    with pytest.raises(MaintenanceInvariantError, match="identity"):
        engine.preflight()


def test_unknown_task_exception_is_not_downgraded(tmp_path: Path) -> None:
    engine, _store = _engine(
        tmp_path,
        archive=_Archive(tmp_path, ()),
        home=_Home(unexpected_failure=True),
    )

    with pytest.raises(AttributeError, match="unexpected"):
        engine.run(
            MaintenanceRequest(
                scope=MaintenanceScope.HOME,
                trigger=MaintenanceTrigger.MANUAL,
            )
        )


def _engine(
    root: Path,
    *,
    archive: "_Archive",
    home: "_Home | None" = None,
    memory: "_Memory | None" = None,
) -> tuple[MaintenanceEngine, MaintenanceAvailabilityStore]:
    store = MaintenanceAvailabilityStore(root / "runtime" / "maintenance")
    return (
        MaintenanceEngine(
            archive=archive,
            home=home or _Home(),
            memory=memory or _Memory(),
            availability_store=store,
            clock=_Clock(),
        ),
        store,
    )


@dataclass
class _Clock:
    current: datetime = datetime(2026, 8, 3, 8, tzinfo=ZoneInfo("Asia/Shanghai"))

    def now(self) -> datetime:
        return self.current

    def today(self) -> BusinessDay:
        return BusinessDay(self.current.date())


class _Archive:
    def __init__(
        self,
        root: Path,
        days: tuple[BusinessDay, ...],
        *,
        transition_day: BusinessDay | None = None,
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
        self.requested_days: list[BusinessDay] = []

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

    def run(self, *, business_day, scope, request_id):
        del business_day, scope, request_id
        if self.unexpected_failure:
            raise AttributeError("unexpected task bug")
        self.runs += 1
        self.pending = False
        return MaintenanceTaskOutcome(
            kind=MaintenanceTaskKind.HOME,
            status=MaintenanceTaskStatus.COMPLETED,
        )


@dataclass
class _Memory:
    existing: set[BusinessDay] = field(default_factory=set)
    ran: list[BusinessDay] = field(default_factory=list)
    fail_days: set[BusinessDay] = field(default_factory=set)

    def eligible(self, day, *, archive, rebuild):
        return archive is not None and (rebuild or day not in self.existing)

    def run(
        self,
        *,
        business_day,
        target_day,
        archive,
        rebuild,
        scope,
        request_id,
    ):
        del business_day, archive, rebuild, scope, request_id
        self.ran.append(target_day)
        if target_day in self.fail_days:
            raise MemoryIOError("known owner failure")
        self.existing.add(target_day)
        return MaintenanceTaskOutcome(
            kind=MaintenanceTaskKind.MEMORY,
            status=MaintenanceTaskStatus.COMPLETED,
            target_day=target_day,
        )
