"""Finish shared Jobs before synchronizing the daily Workspace."""

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.kernel.jobs import JobRegistry
from tinysoul.kernel.loop.interaction.inbox import TurnInbox
from tinysoul.plugins.workspace import WorkspaceEngine, WorkspaceError
from tinysoul.plugins.workspace.errors import WorkspaceReconciliationError
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.runtime import RunScope, SignalBus
from typing import Protocol


class TurnResourceOwner(Protocol):
    async def close_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]: ...


class AgentTurnActivity:
    """Composition of owners, with no additional Job or file state."""

    def __init__(
        self,
        jobs: JobRegistry,
        workspace: WorkspaceEngine,
        resources: tuple[TurnResourceOwner, ...] = (),
    ) -> None:
        self._jobs = jobs
        self._workspace = workspace
        self._resources = resources

    def bind_inbox(self, turn_id: str, inbox: TurnInbox | None) -> None:
        self._jobs.bind_inbox(turn_id, inbox)

    def has_unresolved(self, turn_id: str) -> bool:
        return self._jobs.has_unresolved(turn_id)

    def sync(self, turn_id: str, *, bus: SignalBus, scope: RunScope) -> None:
        self._jobs.sync(turn_id, bus=bus, scope=scope)

    async def cleanup_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        # A required process stop failure must retain the day lease; do not cross
        # the Workspace synchronization boundary until execution has closed.
        diagnostics = await self._jobs.cleanup_turn(turn_id)
        for owner in self._resources:
            diagnostics = (*diagnostics, *await owner.close_turn(turn_id))
        joined = JoinedOperations()
        try:
            result = await joined.run(self._workspace.reconcile)
            if not result.complete:
                raise WorkspaceReconciliationError(
                    "Final Workspace reconciliation is incomplete"
                )
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        await joined.finish(self._workspace.events.flush)
        joined.check_cancelled()
        return diagnostics
