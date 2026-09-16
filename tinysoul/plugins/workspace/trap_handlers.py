"""User Turn trap handlers that integrate Workspace recovery."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.runtime import RunLevel, RuntimeTransfer, TrapResult, TrapSnap
from tinysoul.plugins.workspace import WorkspaceEngine
from tinysoul.plugins.workspace.errors import WorkspaceError
from tinysoul.plugins.workspace.projection import workspace_snapshot_signal

from tinysoul.kernel.loop.errors import LoopInvariantError


@dataclass(frozen=True)
class WorkspaceTrashRestoreTrapHandler:
    """Restore a staged Workspace resource, synchronize Context, and retry."""

    workspace: WorkspaceEngine

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
        except WorkspaceError:
            return _end_user_scope(snap)
        current = snap.scope.current()
        if current is None:
            return _end_user_scope(snap)
        return TrapResult(transfer=RuntimeTransfer.retry(current), signals=(signal,))


def _end_user_scope(snap: TrapSnap) -> TrapResult:
    turn = snap.scope.nearest(RunLevel.TURN)
    if turn is not None:
        return TrapResult(transfer=RuntimeTransfer.end(turn))
    program = snap.scope.nearest(RunLevel.AGENT)
    if program is None:
        raise LoopInvariantError("Runtime scope has no program frame")
    return TrapResult(transfer=RuntimeTransfer.end(program))
