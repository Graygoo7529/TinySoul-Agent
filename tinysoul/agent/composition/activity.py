"""Finish shared Jobs before synchronizing the daily Workspace."""

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.kernel.jobs import JobBackend, JobRegistry
from tinysoul.kernel.loop.interaction.inbox import TurnInbox
from tinysoul.plugins.workspace import WorkspaceEngine, WorkspaceError
from tinysoul.plugins.workspace.errors import WorkspaceReconciliationError
from tinysoul.plugins.workspace.projection import workspace_snapshot_signal
from tinysoul.plugins.workspace.runtime_bridge import RuntimeWorkspaceBridge
from tinysoul.runtime import RunScope, SignalBus


class AgentTurnActivity[B: JobBackend]:
    """Composition of owners, with no additional Job or file state."""

    def __init__(self, jobs: JobRegistry[B], workspace: WorkspaceEngine) -> None:
        self._jobs = jobs
        self._workspace = workspace

    def bind_inbox(self, turn_id: str, inbox: TurnInbox | None) -> None:
        self._jobs.bind_inbox(turn_id, inbox)

    def has_unresolved(self, turn_id: str) -> bool:
        return self._jobs.has_unresolved(turn_id)

    def sync(self, turn_id: str, *, bus: SignalBus, scope: RunScope) -> None:
        self._jobs.sync(turn_id, bus=bus, scope=scope)
        try:
            bus.emit(
                workspace_snapshot_signal(
                    self._workspace.snapshot(),
                    call_id="",
                    scope=scope,
                    source="agent.activity",
                )
            )
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc

    async def cleanup_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        # A required process stop failure must retain the day lease; do not cross
        # the Workspace synchronization boundary until execution has closed.
        diagnostics = await self._jobs.cleanup_turn(turn_id)
        joined = JoinedOperations()
        try:
            result = await joined.run(self._workspace.reconcile)
            if not result.complete:
                raise WorkspaceReconciliationError(
                    "Final Workspace reconciliation is incomplete"
                )
        except WorkspaceError as exc:
            raise RuntimeWorkspaceBridge().from_workspace_error(exc) from exc
        joined.check_cancelled()
        return diagnostics
