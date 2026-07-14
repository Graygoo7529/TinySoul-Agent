from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from tinysoul.home import (
    AgentHomeEngine,
    HomeMaintenanceDecisionProvider,
    HomeMaintenancePending,
    HomeMaintenanceReviewer,
)
from tinysoul.memory import MemoryConsolidator, MemoryEngine
from tinysoul.loop import BusinessDay, DailyLifecycleCoordinator, LoopInvariantError
from tinysoul.loop.maintenance import ProgramMaintenanceRunner
from tinysoul.loop.work import ProgramWorkMode, ProgramWorkStatus
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.session import SessionEngine, SessionMemoryFact, SessionMemoryFactsProjection


TODAY = BusinessDay.parse("2026-07-14")
YESTERDAY = BusinessDay.parse("2026-07-13")


@dataclass
class _AvailabilityHome:
    projection: SessionMemoryFactsProjection

    def maintenance_pending(self) -> HomeMaintenancePending:
        return HomeMaintenancePending(change_count=2, skill_memory_count=1)



@dataclass
class _AvailabilityMemory:
    projection: SessionMemoryFactsProjection

    def exists(self, day: BusinessDay) -> bool:
        assert day == YESTERDAY
        return False

    def maintenance_eligible(
        self,
        projection: SessionMemoryFactsProjection | None,
    ) -> bool:
        return projection is self.projection


@dataclass
class _AvailabilitySession:
    projection: SessionMemoryFactsProjection
    calls: list[tuple[BusinessDay, Path]] = field(default_factory=list)

    def memory_facts(
        self,
        day: BusinessDay,
        *,
        root: Path,
    ) -> SessionMemoryFactsProjection:
        self.calls.append((day, root))
        return self.projection


@dataclass
class _AvailabilityDaily:
    archive: Path
    days: list[BusinessDay] = field(default_factory=list)

    def session_archive_for(self, day: BusinessDay) -> Path:
        self.days.append(day)
        return self.archive


class _ExistingMemory:
    def exists(self, day: BusinessDay) -> bool:
        assert day == YESTERDAY
        return True


class _UnexpectedDaily:
    def session_archive_for(self, day: BusinessDay) -> Path:
        raise AssertionError("Existing automatic MEMORY must skip Session loading")


class _BrokenDaily:
    def session_archive_for(self, day: BusinessDay) -> Path:
        raise LoopInvariantError("archive index is inconsistent")


def test_maintenance_availability_uses_yesterday_session_projection() -> None:
    projection = _projection()
    home = _AvailabilityHome(projection)
    session = _AvailabilitySession(projection)
    daily = _AvailabilityDaily(Path("archive/session"))
    runner = _runner(
        home=home,
        memory=_AvailabilityMemory(projection),
        session=session,
        daily=daily,
    )

    availability = runner.availability(TODAY)

    assert availability.home_pending is True
    assert availability.home_change_count == 2
    assert availability.home_skill_memory_count == 1
    assert availability.memory_pending is True
    assert availability.memory_day == YESTERDAY
    assert daily.days == [YESTERDAY]
    assert session.calls == [(YESTERDAY, Path("archive/session"))]


def test_automatic_existing_memory_skips_before_session_loading() -> None:
    runner = _runner(
        home=_AvailabilityHome(_projection()),
        memory=_ExistingMemory(),
        session=object(),
        daily=_UnexpectedDaily(),
    )

    outcome = runner.run_memory(
        business_day=TODAY,
        target_day=YESTERDAY,
        mode=ProgramWorkMode.AUTOMATIC,
        source="scheduler",
        scope=RunScope().push(RunLevel.PROGRAM, "program"),
    )

    assert outcome.status is ProgramWorkStatus.SKIPPED
    assert outcome.details["skip_reason"] == "memory_exists"


def test_memory_archive_failure_is_a_failed_work_outcome() -> None:
    runner = _runner(
        home=_AvailabilityHome(_projection()),
        memory=_AvailabilityMemory(_projection()),
        session=object(),
        daily=_BrokenDaily(),
    )

    outcome = runner.run_memory(
        business_day=TODAY,
        target_day=YESTERDAY,
        mode=ProgramWorkMode.MANUAL,
        source="terminal",
        scope=RunScope().push(RunLevel.PROGRAM, "program"),
    )

    assert outcome.status is ProgramWorkStatus.FAILED
    assert outcome.details["error_type"] == "LoopInvariantError"


def _runner(
    *,
    home: object,
    memory: object,
    session: object,
    daily: object,
) -> ProgramMaintenanceRunner:
    unused = object()
    return ProgramMaintenanceRunner(
        home=cast(AgentHomeEngine, home),
        memory=cast(MemoryEngine, memory),
        session=cast(SessionEngine, session),
        daily_lifecycle=cast(DailyLifecycleCoordinator, daily),
        timezone="Asia/Shanghai",
        automatic_home_reviewer=cast(HomeMaintenanceReviewer, unused),
        memory_consolidator=cast(MemoryConsolidator, unused),
        manual_home_decisions=cast(HomeMaintenanceDecisionProvider, unused),
    )


def _projection() -> SessionMemoryFactsProjection:
    return SessionMemoryFactsProjection(
        day=YESTERDAY,
        revision=1,
        facts=(
            SessionMemoryFact(
                ref="session:turn/turn_1",
                started_at=datetime(2026, 7, 13, 9, tzinfo=UTC),
                user_inputs=("fact",),
            ),
        ),
    )
