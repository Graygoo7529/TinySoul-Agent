"""Memory Maintenance target readiness and Turn orchestration."""

from __future__ import annotations

from tinysoul.infra.time import BusinessDay
from tinysoul.memory import MemoryEngine, MemoryIOError
from tinysoul.runtime import RunScope
from tinysoul.session import SessionEngine, SessionIOError
from tinysoul.workspace import WorkspaceEngine, WorkspaceIOError

from ..archive import ArchiveProjection
from ..errors import MaintenanceTaskExecutionError
from ..models import MaintenanceTaskKind, MaintenanceTaskOutcome, MaintenanceTaskStatus
from ..turn import MaintenanceTurnEntry
from .actions import MemoryMaintenanceActionController
from .context import ArchivedMemoryMaintenanceContext


class MemoryMaintenanceTask:
    """Bind one closed Business Day to the common Memory Maintenance Turn."""

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        session: SessionEngine,
        workspace: WorkspaceEngine,
        archived_context: ArchivedMemoryMaintenanceContext,
        controller: MemoryMaintenanceActionController,
        turn: MaintenanceTurnEntry,
    ) -> None:
        self._memory = memory
        self._session = session
        self._workspace = workspace
        self._archived_context = archived_context
        self._controller = controller
        self._turn = turn

    def recover(self) -> None:
        self._memory.recover()

    def eligible(
        self,
        day: BusinessDay,
        *,
        archive: ArchiveProjection | None,
        if_absent: bool,
    ) -> bool:
        if archive is None:
            return False
        if if_absent and self._memory.read_daily(day) is not None:
            return False
        if not self._session.archive_available(day, root=archive.session_root):
            return False
        if not self._memory.archived_active_available(day, archive.session_root):
            return False
        projection = self._session.memory_facts(day, root=archive.session_root)
        active = self._memory.validate_archived_active(day, archive.session_root)
        return bool(projection.facts or active.content.strip())

    def run(
        self,
        *,
        business_day: BusinessDay,
        target_day: BusinessDay,
        archive: ArchiveProjection | None,
        scope: RunScope,
        request_id: str,
    ) -> MaintenanceTaskOutcome:
        if target_day >= business_day:
            return _skipped(target_day, "target_day_is_open")
        if archive is None:
            return _skipped(target_day, "archive_missing")
        if not self._session.archive_available(target_day, root=archive.session_root):
            return _skipped(target_day, "session_missing")
        if not self._memory.archived_active_available(
            target_day,
            archive.session_root,
        ):
            return _skipped(target_day, "active_memory_missing")
        projection = self._session.memory_facts(target_day, root=archive.session_root)
        active = self._memory.validate_archived_active(target_day, archive.session_root)
        if not projection.facts and not active.content.strip():
            return _skipped(target_day, "target_sources_empty")
        workspace = self._workspace.archive_view(target_day, root=archive.workspace_root)
        session_view = self._session.archive_view(target_day, root=archive.session_root)
        completed = False
        try:
            self._archived_context.bind(
                target_day=target_day,
                session=session_view,
                workspace=workspace,
                active_memory=active,
            )
            self._controller.begin(
                target_day=target_day,
                projection=projection,
                active_memory=active,
                workspace=workspace,
            )
            outcome = self._turn.run(
                (
                    "Maintain daily, entity, concept, fact, and note Memory for the "
                    f"closed Business Day {target_day}. Inspect and reuse existing "
                    "Memory before creating. Compose and stage the complete target daily, "
                    "preview the full draft, commit it, then complete the task."
                ),
                business_day=target_day,
                scope=scope,
                request_id=request_id,
                input_source="maintenance.memory",
            )
            if not outcome.completed:
                self._controller.abort()
                completed = True
                return MaintenanceTaskOutcome(
                    kind=MaintenanceTaskKind.MEMORY,
                    status=MaintenanceTaskStatus.FAILED,
                    target_day=target_day,
                    reason="maintenance_turn_failed",
                    details=outcome.details,
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
