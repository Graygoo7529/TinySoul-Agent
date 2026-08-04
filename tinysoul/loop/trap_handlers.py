"""Trap handlers used by the loop assembly layer."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.runtime import (
    RunFrame,
    RunLevel,
    RuntimeTransfer,
    TrapResult,
    TrapSnap,
)
from tinysoul.context import ContextEngine, ContextSignalBatch
from tinysoul.context.errors import ContextError
from tinysoul.workspace import WorkspaceEngine
from tinysoul.workspace.errors import WorkspaceError
from tinysoul.workspace.projection import workspace_snapshot_signal

from .errors import LoopInvariantError
from .pressure import ContextPressureRecovery


@dataclass(frozen=True)
class EndFrameTrapHandler:
    """End the nearest runtime frame at the configured level."""

    level: RunLevel

    def handle(self, snap: TrapSnap) -> TrapResult:
        return TrapResult(transfer=RuntimeTransfer.end(_nearest(snap, self.level)))


@dataclass(frozen=True)
class RetryCurrentFrameTrapHandler:
    """Retry the current runtime frame."""

    def handle(self, snap: TrapSnap) -> TrapResult:
        current = snap.scope.current()
        if current is None:
            raise LoopInvariantError("Cannot retry an empty runtime scope")
        return TrapResult(transfer=RuntimeTransfer.retry(current))


@dataclass(frozen=True)
class EndTurnOrProgramTrapHandler:
    """End the nearest user-visible frame for an unhandled runtime failure."""

    def handle(self, snap: TrapSnap) -> TrapResult:
        turn = snap.scope.nearest(RunLevel.TURN)
        if turn is not None:
            return TrapResult(transfer=RuntimeTransfer.end(turn))
        return TrapResult(
            transfer=RuntimeTransfer.end(_nearest(snap, RunLevel.PROGRAM))
        )


@dataclass(frozen=True)
class ContextPressureTrapHandler:
    """Relieve context pressure and retry the narrowest replayable frame."""

    recovery: ContextPressureRecovery

    def handle(self, snap: TrapSnap) -> TrapResult:
        report = self.recovery.recover(payload=snap.payload, scope=snap.scope)
        if report.changed:
            module = snap.scope.nearest(RunLevel.MODULE)
            if module is not None:
                return TrapResult(transfer=RuntimeTransfer.retry(module))
            phase = snap.scope.nearest(RunLevel.PHASE)
            if phase is not None:
                return TrapResult(transfer=RuntimeTransfer.retry(phase))
        turn = snap.scope.nearest(RunLevel.TURN)
        if turn is not None:
            return TrapResult(transfer=RuntimeTransfer.end(turn))
        return TrapResult(transfer=RuntimeTransfer.end(_nearest(snap, RunLevel.PROGRAM)))


@dataclass(frozen=True)
class WorkspaceTrashRestoreTrapHandler:
    """Restore a staged Workspace resource, synchronize Context, and retry."""

    workspace: WorkspaceEngine
    context: ContextEngine

    def handle(self, snap: TrapSnap) -> TrapResult:
        link = snap.payload.get("link")
        trash_ref = snap.payload.get("trash_ref")
        turn = snap.scope.nearest(RunLevel.TURN)
        if (
            not isinstance(link, str)
            or not link
            or not isinstance(trash_ref, str)
            or not trash_ref
            or turn is None
        ):
            return _end_user_scope(snap)
        try:
            record = self.workspace.restore_resource(trash_ref)
            if record.link != link:
                raise LoopInvariantError(
                    "Workspace Trash restore returned a different resource link"
                )
            signal = workspace_snapshot_signal(
                self.workspace.snapshot(),
                call_id=f"trash_restore:{trash_ref}",
                scope=snap.scope,
                source="loop.workspace_trash_restore",
            )
            results = self.context.consume_signal_batch(
                ContextSignalBatch(turn_id=turn.name, signals=(signal,))
            )
            if results:
                self.workspace.trash_resource(
                    link,
                    reason="trash_restore_context_rejected",
                    source_turn_id=turn.name,
                )
                return _end_user_scope(snap)
        except (ContextError, WorkspaceError):
            return _end_user_scope(snap)
        current = snap.scope.current()
        if current is None:
            return _end_user_scope(snap)
        return TrapResult(transfer=RuntimeTransfer.retry(current))


def _nearest(snap: TrapSnap, level: RunLevel) -> RunFrame:
    frame = snap.scope.nearest(level)
    if frame is None:
        raise LoopInvariantError(f"Runtime scope has no {level.value} frame")
    return frame


def _end_user_scope(snap: TrapSnap) -> TrapResult:
    turn = snap.scope.nearest(RunLevel.TURN)
    if turn is not None:
        return TrapResult(transfer=RuntimeTransfer.end(turn))
    return TrapResult(transfer=RuntimeTransfer.end(_nearest(snap, RunLevel.PROGRAM)))
