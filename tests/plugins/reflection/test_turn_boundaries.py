from __future__ import annotations

from contextlib import asynccontextmanager
from tinysoul.infra.concurrency import AsyncMailbox
from pathlib import Path
from typing import cast

import pytest

from tinysoul.agent.dispatch.scheduler import RootScheduler
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.loop import TurnOutcomeStatus
from tinysoul.kernel.loop.lifecycle.preparation import TurnPreparationRequest
from tinysoul.kernel.loop.trap_handlers import EndFrameTrapHandler
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.plugins.archive import DailyTransitionOutcome
from tinysoul.plugins.reflection import (
    ReflectionAvailability,
    ReflectionEngine,
    ReflectionInvariantError,
    ReflectionRequest,
    ReflectionScope,
    ReflectionTaskKind,
    ReflectionTaskOutcome,
    ReflectionTaskStatus,
    ReflectionTrigger,
)
from tinysoul.plugins.reflection.turn import ReflectionTurnEntry
from tinysoul.plugins.reflection.memory import MemoryReflectionContext
from tinysoul.plugins.memory import ActiveMemoryDocument
from tinysoul.runtime import (
    RUNTIME_AGENT_END,
    RunLevel,
    RunScope,
    RuntimeTransfer,
    RuntimeTransferInterrupt,
    RuntimeTrap,
    SignalBus,
    TrapHandlerRegistry,
)
from tinysoul.plugins.session import SessionEngine, SessionSettings
from tinysoul.plugins.workspace import WorkspaceArchiveView, WorkspaceManifest

DAY = CalendarDay.parse("2026-08-03")


async def test_outer_turn_transfer_is_unwound_without_downgrade() -> None:
    scope = RunScope().push(RunLevel.AGENT, "program")
    agent_frame = scope.current()
    assert agent_frame is not None
    transfer = RuntimeTransfer.end(agent_frame)
    outcome = TurnOutcome(
        context_completion=None,
        business_day=DAY,
        status=TurnOutcomeStatus.STOPPED,
        transfer=transfer,
    )

    entry = ReflectionTurnEntry(_TurnRunner(outcome), kind="home")
    with pytest.raises(RuntimeTransferInterrupt) as captured:
        await entry.run(
            "review home",
            business_day=DAY,
            scope=scope,
            request_id="request",
            input_source="test",
        )

    assert captured.value.transfer == transfer


async def test_program_converts_reflection_error_to_program_transfer() -> None:
    runner = RootScheduler(
        user_turn=_UserTurn(),
        reflection=_FailingReflection(),
        day=_FailingReflection(),
        bus=SignalBus(),
        trap=_agent_trap(),
    )
    runner.submit_turn(
        ReflectionRequest(
            scope=ReflectionScope.HOME,
            trigger=ReflectionTrigger.MANUAL,
        )
    )

    outcome = await runner.run()

    assert outcome.transfer is not None
    assert outcome.transfer.target.level is RunLevel.AGENT
    assert outcome.reflection_count == 0


async def test_reflection_engine_does_not_add_fake_module_frames(
    tmp_path: Path,
) -> None:
    scope = RunScope().push(RunLevel.AGENT, "program")
    archive = _ScopeArchive()
    home = _ScopeHome()
    engine = ReflectionEngine(
        archive=archive,
        home=home,
        memory=_ScopeMemory(),
    )

    await engine.run(
        ReflectionRequest(
            scope=ReflectionScope.HOME,
            trigger=ReflectionTrigger.MANUAL,
        ),
        scope=scope,
        business_day=DAY,
    )

    assert archive.scopes == []
    assert home.scopes == [scope]
    assert all(frame.level is not RunLevel.MODULE for frame in scope)


def test_archived_memory_context_rejects_mismatched_owner_days(tmp_path: Path) -> None:
    context = MemoryReflectionContext()
    other_day = CalendarDay.parse("2026-08-02")

    with pytest.raises(ReflectionInvariantError, match="Session day"):
        context.bind(
            target_day=DAY,
            session=SessionEngine(
                SessionSettings(root=tmp_path / "session")
            ).empty_view(other_day),
            workspace=None,
            active_memory=_active(DAY),
        )

    with pytest.raises(ReflectionInvariantError, match="Workspace day"):
        context.bind(
            target_day=DAY,
            session=SessionEngine(
                SessionSettings(root=tmp_path / "session")
            ).empty_view(DAY),
            workspace=WorkspaceArchiveView(
                root=Path("."),
                manifest=WorkspaceManifest(day=str(other_day)),
                max_read_chars=1024,
            ),
            active_memory=_active(DAY),
        )


def test_archived_memory_context_retains_source_day_independently_of_turn_day(
    tmp_path: Path,
) -> None:
    context = MemoryReflectionContext()
    context.bind(
        target_day=DAY,
        session=SessionEngine(SessionSettings(root=tmp_path / "session")).empty_view(
            DAY
        ),
        workspace=WorkspaceArchiveView(
            root=Path("."),
            manifest=WorkspaceManifest(day=str(DAY)),
            max_read_chars=1024,
        ),
        active_memory=_active(DAY),
    )
    assert context.source_day() == DAY
    assert context.source_workspace() is not None
    assert context.memory_target()[0] == DAY.value
    with pytest.raises(ReflectionInvariantError, match="source day"):
        context.background_snapshot(CalendarDay.parse("2026-08-02"))


class _UserTurn:
    async def run(
        self, turn_input, *, business_day, scope, request_id, input_source, inbox=None
    ):
        del turn_input, scope, request_id, input_source
        return TurnOutcome(
            context_completion=None,
            business_day=business_day,
            status=TurnOutcomeStatus.STOPPED,
        )


class _TurnRunner:
    def __init__(self, outcome):
        self._outcome = outcome

    async def run(
        self, turn_input, *, business_day, scope, request_id, input_source, inbox=None
    ):
        del turn_input, business_day, scope, request_id, input_source
        return self._outcome


class _FailingReflection:
    @property
    def active_day(self):
        return self.current_day()

    def current_day(self):
        return CalendarDay.parse("2026-08-03")

    @asynccontextmanager
    async def active_day_lease(self):
        yield DAY

    async def preflight(self, *, scope=None):
        del scope
        return DailyTransitionOutcome(active_day=DAY)

    def availability(self):
        return ReflectionAvailability(checked_day=DAY)

    def refresh_availability(self, transition, *, scope):
        return self.availability()

    async def run(self, request, *, business_day, scope=None, inbox=None):
        del request, scope
        raise ReflectionInvariantError("reflection invariant")


class _Clock:
    def now(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime(2026, 8, 3, 8, tzinfo=ZoneInfo("Asia/Shanghai"))

    def today(self):
        return DAY


class _ScopeArchive:
    def __init__(self):
        self.scopes = []

    @asynccontextmanager
    async def active_day_lease(self):
        yield DAY

    def ensure_active_day(self, target_day, *, now, scope):
        del now
        self.scopes.append(scope)
        return DailyTransitionOutcome(active_day=target_day)

    def archived_days(self, *, before=None, limit=64):
        return ()

    def archive_for(self, day):
        del day
        return None


class _ScopeHome:
    def __init__(self):
        self.scopes = []

    def pending_counts(self):
        return (0, 0)

    async def run(
        self, *, business_day, scope, request_id, inbox=None, instructions=""
    ):
        del business_day, request_id
        self.scopes.append(scope)
        return ReflectionTaskOutcome(
            kind=ReflectionTaskKind.HOME,
            status=ReflectionTaskStatus.COMPLETED,
        )


class _ScopeMemory:
    def recover(self) -> None:
        return None

    def daily_days(self, *, before=None, limit=64):
        return ()

    def has_daily(self, day):
        return False

    def eligible(self, day, *, archive):
        del day, archive
        return False

    async def run(self, **kwargs):
        del kwargs
        return ReflectionTaskOutcome(
            kind=ReflectionTaskKind.MEMORY,
            status=ReflectionTaskStatus.SKIPPED,
        )


def _active(day: CalendarDay) -> ActiveMemoryDocument:
    return ActiveMemoryDocument(
        day=day.value, updated_at=None, content="Archived memory."
    )


def _agent_trap() -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_AGENT_END, EndFrameTrapHandler(RunLevel.AGENT))
    return RuntimeTrap(registry=registry)
