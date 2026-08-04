"""User Turn trap handlers that integrate Workspace recovery."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.context import ContextEngine, ContextSignalBatch
from tinysoul.context.errors import ContextError
from tinysoul.runtime import RunLevel, RuntimeTransfer, TrapResult, TrapSnap
from tinysoul.workspace import WorkspaceEngine
from tinysoul.workspace.errors import WorkspaceError
from tinysoul.workspace.projection import workspace_snapshot_signal

from ..errors import LoopInvariantError


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
                source="loop.user.workspace_trash_restore",
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


def _end_user_scope(snap: TrapSnap) -> TrapResult:
    turn = snap.scope.nearest(RunLevel.TURN)
    if turn is not None:
        return TrapResult(transfer=RuntimeTransfer.end(turn))
    program = snap.scope.nearest(RunLevel.PROGRAM)
    if program is None:
        raise LoopInvariantError("Runtime scope has no program frame")
    return TrapResult(transfer=RuntimeTransfer.end(program))
