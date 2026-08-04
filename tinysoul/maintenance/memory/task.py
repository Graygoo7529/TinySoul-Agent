"""Memory Maintenance task orchestration around a Maintenance Turn."""

from __future__ import annotations

from tinysoul.infra.time import BusinessDay
from tinysoul.loop import TurnOutcomeStatus
from tinysoul.loop.turn import TurnRunner
from tinysoul.memory import MemoryEngine, MemoryIOError
from tinysoul.runtime import RunScope
from tinysoul.session import SessionEngine, SessionIOError
from tinysoul.workspace import WorkspaceEngine, WorkspaceIOError

from ..archive import ArchiveProjection
from ..errors import MaintenanceTaskExecutionError
from ..models import (
    MaintenanceTaskKind,
    MaintenanceTaskOutcome,
    MaintenanceTaskStatus,
)
from ..turn_boundary import propagate_outer_turn_transfer, turn_failure_details
from .actions import MemoryMaintenanceActionController
from .context import ArchivedMemoryMaintenanceContext


class MemoryMaintenanceTask:
    """Build closed-day projections and consolidate durable Memory through a Turn."""

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        session: SessionEngine,
        workspace: WorkspaceEngine,
        archived_context: ArchivedMemoryMaintenanceContext,
        controller: MemoryMaintenanceActionController,
        turn: TurnRunner,
    ) -> None:
        self._memory = memory
        self._session = session
        self._workspace = workspace
        self._archived_context = archived_context
        self._controller = controller
        self._turn = turn

    def eligible(
        self,
        day: BusinessDay,
        *,
        archive: ArchiveProjection | None,
        rebuild: bool,
    ) -> bool:
        if archive is None:
            return False
        if not rebuild and self._memory.read_day(day) is not None:
            return False
        projection = self._session.memory_facts(day, root=archive.session_root)
        return self._memory.maintenance_eligible(projection)

    def run(
        self,
        *,
        business_day: BusinessDay,
        target_day: BusinessDay,
        archive: ArchiveProjection | None,
        rebuild: bool,
        scope: RunScope,
        request_id: str,
    ) -> MaintenanceTaskOutcome:
        if target_day >= business_day:
            return _skipped(target_day, "target_day_is_open")
        if archive is None:
            return _skipped(target_day, "archive_missing")
        if not rebuild and self._memory.read_day(target_day) is not None:
            return _skipped(target_day, "memory_exists")

        projection = self._session.memory_facts(
            target_day,
            root=archive.session_root,
        )
        if not self._memory.maintenance_eligible(projection):
            return _skipped(target_day, "session_facts_empty")
        workspace = self._workspace.archive_snapshot(
            target_day,
            root=archive.workspace_root,
        )
        session_view = self._session.archive_view(
            target_day,
            root=archive.session_root,
        )
        completed = False
        try:
            self._archived_context.bind(
                target_day=target_day,
                session=session_view,
                workspace=workspace,
            )
            self._controller.begin(
                target_day=target_day,
                projection=projection,
                workspace=workspace,
                rebuild_memory=rebuild,
            )
            outcome = self._turn.run(
                (
                    "Consolidate durable Memory for the closed Business Day "
                    f"{target_day}. Treat that closed day and its archived timestamps "
                    "as this Turn's temporal context, not the wall-clock execution day."
                ),
                business_day=target_day,
                scope=scope,
                request_id=request_id,
                input_source="maintenance.memory",
            )
            propagate_outer_turn_transfer(outcome)
            if (
                outcome.status is not TurnOutcomeStatus.COMPLETED
                or outcome.completion is None
                or outcome.completion.get("task") != "memory"
            ):
                self._controller.abort()
                completed = True
                return MaintenanceTaskOutcome(
                    kind=MaintenanceTaskKind.MEMORY,
                    status=MaintenanceTaskStatus.FAILED,
                    target_day=target_day,
                    reason="maintenance_turn_failed",
                    details=turn_failure_details(outcome),
                )
            result = MaintenanceTaskOutcome(
                kind=MaintenanceTaskKind.MEMORY,
                status=MaintenanceTaskStatus.COMPLETED,
                target_day=target_day,
                details=self._controller.finish(),
            )
            completed = True
            return result
        except (MemoryIOError, SessionIOError, WorkspaceIOError) as exc:
            raise MaintenanceTaskExecutionError("Memory Maintenance task failed") from exc
        finally:
            if not completed:
                self._controller.abort()
            self._archived_context.clear()


def _skipped(day: BusinessDay, reason: str) -> MaintenanceTaskOutcome:
    return MaintenanceTaskOutcome(
        kind=MaintenanceTaskKind.MEMORY,
        status=MaintenanceTaskStatus.SKIPPED,
        target_day=day,
        reason=reason,
    )
