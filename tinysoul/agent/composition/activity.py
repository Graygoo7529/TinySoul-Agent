"""Finish shared Jobs before synchronizing the daily Workspace."""

from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.kernel.jobs import JobRegistry
from tinysoul.kernel.loop.interaction.inbox import TurnInbox
from tinysoul.kernel.registration import PluginTurnResource
from tinysoul.runtime import RunScope, SignalBus


class AgentTurnActivity:
    """Composition of owners, with no additional Job or file state."""

    def __init__(
        self,
        jobs: JobRegistry,
        resources: tuple[PluginTurnResource, ...] = (),
    ) -> None:
        self._jobs = jobs
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
        for resource in self._resources:
            diagnostics = (*diagnostics, *await resource.owner.close_turn(turn_id))
        return diagnostics
