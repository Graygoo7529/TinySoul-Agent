from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tinysoul.maintenance import (
    ArchiveProjection,
    BusinessDay,
    DailyTransitionOutcome,
    MaintenanceEngine,
    MaintenanceInvariantError,
    MaintenanceRequest,
    MaintenanceScope,
    MaintenanceTaskKind,
    MaintenanceTaskOutcome,
    MaintenanceTaskStatus,
    MaintenanceTrigger,
)
from tinysoul.runtime import RunScope


TODAY = BusinessDay.parse("2026-08-03")
DAY_ONE = BusinessDay.parse("2026-08-01")
DAY_TWO = BusinessDay.parse("2026-08-02")


def test_daily_maintenance_processes_home_and_all_missed_memory_days(
    tmp_path: Path,
) -> None:
    archive = _Archive(tmp_path, (DAY_ONE, DAY_TWO))
    home = _Home(pending=True)
    memory = _Memory()
    engine = MaintenanceEngine(
        archive=archive,
        home=home,
        memory=memory,
        clock=_Clock(),
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


def test_manual_and_scheduled_home_requests_use_the_same_task_path(
    tmp_path: Path,
) -> None:
    outcomes = []
    homes = []
    for trigger in (MaintenanceTrigger.MANUAL, MaintenanceTrigger.SCHEDULED):
        home = _Home(pending=True)
        homes.append(home)
        engine = MaintenanceEngine(
            archive=_Archive(tmp_path, ()),
            home=home,
            memory=_Memory(),
            clock=_Clock(),
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


def test_explicit_memory_rebuild_targets_only_requested_closed_day(
    tmp_path: Path,
) -> None:
    memory = _Memory(existing={DAY_ONE})
    engine = MaintenanceEngine(
        archive=_Archive(tmp_path, (DAY_ONE, DAY_TWO)),
        home=_Home(),
        memory=memory,
        clock=_Clock(),
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


def test_archive_outcome_requires_authoritative_catalog_identity(
    tmp_path: Path,
) -> None:
    engine = MaintenanceEngine(
        archive=_Archive(tmp_path, ()),
        home=_Home(),
        memory=_Memory(),
        clock=_Clock(),
    )
    transition = DailyTransitionOutcome(
        active_day=TODAY,
        archive_path=(tmp_path / "unknown-archive").resolve(),
    )

    with pytest.raises(MaintenanceInvariantError, match="authoritative catalog"):
        engine.plan(
            MaintenanceRequest(
                scope=MaintenanceScope.DAILY,
                trigger=MaintenanceTrigger.MANUAL,
            ),
            transition=transition,
        )


@dataclass
class _Clock:
    current: datetime = datetime(2026, 8, 3, 8, tzinfo=ZoneInfo("Asia/Shanghai"))

    def now(self) -> datetime:
        return self.current

    def today(self) -> BusinessDay:
        return BusinessDay(self.current.date())


class _Archive:
    def __init__(self, root: Path, days: tuple[BusinessDay, ...]) -> None:
        self._days = days
        self._projections = {
            day: ArchiveProjection(
                day=day,
                root=(root / str(day)).resolve(),
                session_root=(root / str(day) / "session").resolve(),
                workspace_root=(root / str(day) / "workspace").resolve(),
            )
            for day in days
        }

    def ensure_active_day(self, target_day, *, now, scope=None):
        del now, scope
        return DailyTransitionOutcome(active_day=target_day)

    @contextmanager
    def active_day_lease(self):
        yield TODAY

    def closed_days(self):
        return self._days

    def archive_for(self, day):
        return self._projections.get(day)


@dataclass
class _Home:
    pending: bool = False
    runs: int = 0

    def pending_counts(self) -> tuple[int, int]:
        return (1, 0) if self.pending else (0, 0)

    def run(self, *, business_day, scope, request_id):
        del business_day, scope, request_id
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
        self.existing.add(target_day)
        return MaintenanceTaskOutcome(
            kind=MaintenanceTaskKind.MEMORY,
            status=MaintenanceTaskStatus.COMPLETED,
            target_day=target_day,
        )
