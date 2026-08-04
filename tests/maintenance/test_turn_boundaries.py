from __future__ import annotations

from contextlib import contextmanager
from queue import Queue
from pathlib import Path
from typing import cast

import pytest

from tinysoul.app.program import ProgramRunner
from tinysoul.infra.time import BusinessDay
from tinysoul.loop import TurnOutcomeStatus
from tinysoul.loop.preparation import TurnPreparationRequest
from tinysoul.loop.trap_handlers import EndFrameTrapHandler
from tinysoul.loop.turn import TurnOutcome
from tinysoul.maintenance import (
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
from tinysoul.maintenance.turn_boundary import propagate_outer_turn_transfer
from tinysoul.maintenance.memory import ArchivedMemoryMaintenanceContext
from tinysoul.runtime import (
    RUNTIME_PROGRAM_END,
    RunLevel,
    RunScope,
    RuntimeTransfer,
    RuntimeTransferInterrupt,
    RuntimeTrap,
    SignalBus,
    TrapHandlerRegistry,
)
from tinysoul.session import SessionArchiveView, SessionEngine
from tinysoul.workspace import WorkspaceManifest


DAY = BusinessDay.parse("2026-08-03")


def test_outer_turn_transfer_is_unwound_without_downgrade() -> None:
    scope = RunScope().push(RunLevel.PROGRAM, "program")
    program_frame = scope.current()
    assert program_frame is not None
    transfer = RuntimeTransfer.end(program_frame)
    outcome = TurnOutcome(
        context_completion=None,
        business_day=DAY,
        status=TurnOutcomeStatus.STOPPED,
        transfer=transfer,
    )

    with pytest.raises(RuntimeTransferInterrupt) as captured:
        propagate_outer_turn_transfer(outcome)

    assert captured.value.transfer == transfer


def test_program_converts_maintenance_error_to_program_transfer() -> None:
    runner = ProgramRunner(
        user_turn=_UserTurn(),
        maintenance=_FailingMaintenance(),
        bus=SignalBus(),
        trap=_program_trap(),
        input_queue=Queue(),
    )
    runner.input_queue.put(
        MaintenanceRequest(
            scope=MaintenanceScope.HOME,
            trigger=MaintenanceTrigger.MANUAL,
        )
    )

    outcome = runner.run()

    assert outcome.transfer is not None
    assert outcome.transfer.target.level is RunLevel.PROGRAM
    assert outcome.maintenance_count == 0


def test_maintenance_engine_does_not_add_fake_module_frames(tmp_path: Path) -> None:
    scope = RunScope().push(RunLevel.PROGRAM, "program")
    archive = _ScopeArchive()
    home = _ScopeHome()
    engine = MaintenanceEngine(
        archive=archive,
        home=home,
        memory=_ScopeMemory(),
        availability_store=MaintenanceAvailabilityStore(tmp_path / "runtime"),
        clock=_Clock(),
    )

    engine.run(
        MaintenanceRequest(
            scope=MaintenanceScope.HOME,
            trigger=MaintenanceTrigger.MANUAL,
        ),
        scope=scope,
    )

    assert archive.scopes == [scope]
    assert home.scopes == [scope]
    assert all(frame.level is not RunLevel.MODULE for frame in scope)


def test_archived_memory_context_rejects_mismatched_owner_days() -> None:
    context = ArchivedMemoryMaintenanceContext()
    other_day = BusinessDay.parse("2026-08-02")

    with pytest.raises(MaintenanceInvariantError, match="Session day"):
        context.bind(
            target_day=DAY,
            session=SessionArchiveView(
                day=other_day,
                engine=cast(SessionEngine, _ArchiveSession()),
            ),
            workspace=None,
        )

    with pytest.raises(MaintenanceInvariantError, match="Workspace day"):
        context.bind(
            target_day=DAY,
            session=SessionArchiveView(
                day=DAY,
                engine=cast(SessionEngine, _ArchiveSession()),
            ),
            workspace=WorkspaceManifest(day=str(other_day)),
        )


def test_archived_memory_context_rejects_mismatched_turn_day() -> None:
    context = ArchivedMemoryMaintenanceContext()
    context.bind(
        target_day=DAY,
        session=SessionArchiveView(
            day=DAY,
            engine=cast(SessionEngine, _ArchiveSession()),
        ),
        workspace=WorkspaceManifest(day=str(DAY)),
    )
    scope = (
        RunScope()
        .push(RunLevel.PROGRAM, "program")
        .push(RunLevel.TURN, "turn_memory")
    )

    with pytest.raises(MaintenanceInvariantError, match="BusinessDay"):
        context.prepare(
            TurnPreparationRequest(
                turn_id="turn_memory",
                turn_input="maintain memory",
                business_day=BusinessDay.parse("2026-08-02"),
                scope=scope,
            )
        )


class _UserTurn:
    def run(self, turn_input, *, business_day, scope, request_id, input_source):
        del turn_input, scope, request_id, input_source
        return TurnOutcome(
            context_completion=None,
            business_day=business_day,
            status=TurnOutcomeStatus.STOPPED,
        )


class _FailingMaintenance:
    @contextmanager
    def active_day_lease(self):
        yield DAY

    def preflight(self, *, scope=None):
        del scope
        return DailyTransitionOutcome(active_day=DAY)

    def availability(self):
        return MaintenanceAvailability(checked_day=DAY)

    def run(self, request, *, scope=None):
        del request, scope
        raise MaintenanceInvariantError("maintenance invariant")


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

    @contextmanager
    def active_day_lease(self):
        yield DAY

    def ensure_active_day(self, target_day, *, now, scope):
        del now
        self.scopes.append(scope)
        return DailyTransitionOutcome(active_day=target_day)

    def archive_for(self, day):
        del day
        return None


class _ScopeHome:
    def __init__(self):
        self.scopes = []

    def pending_counts(self):
        return (0, 0)

    def run(self, *, business_day, scope, request_id):
        del business_day, request_id
        self.scopes.append(scope)
        return MaintenanceTaskOutcome(
            kind=MaintenanceTaskKind.HOME,
            status=MaintenanceTaskStatus.COMPLETED,
        )


class _ScopeMemory:
    def eligible(self, day, *, archive, rebuild):
        del day, archive, rebuild
        return False

    def run(self, **kwargs):
        del kwargs
        return MaintenanceTaskOutcome(
            kind=MaintenanceTaskKind.MEMORY,
            status=MaintenanceTaskStatus.SKIPPED,
        )


class _ArchiveSession:
    def background_snapshot(self, day):
        raise AssertionError(f"unexpected background read for {day}")

    def inspect(self, ref=None, *, action=None, continuation=None):
        del ref, action, continuation
        return {}


def _program_trap() -> RuntimeTrap:
    registry = TrapHandlerRegistry()
    registry.register(RUNTIME_PROGRAM_END, EndFrameTrapHandler(RunLevel.PROGRAM))
    return RuntimeTrap(registry=registry)
