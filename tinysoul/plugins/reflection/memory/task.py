"""Memory Reflection target readiness and Turn orchestration."""

from __future__ import annotations

from tinysoul.infra.time import CalendarDay
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.plugins.memory import MemoryEngine, MemoryIOError
from tinysoul.runtime import RunScope
from tinysoul.kernel.loop.inbox import TurnInbox
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.plugins.session import SessionEngine, SessionIOError
from tinysoul.plugins.workspace import WorkspaceEngine, WorkspaceIOError

from tinysoul.plugins.archive import ArchiveProjection
from ..errors import ReflectionTaskExecutionError
from ..models import ReflectionTaskKind, ReflectionTaskOutcome, ReflectionTaskStatus
from ..turn import ReflectionTurnEntry
from .actions import MemoryReflectionActionController
from .context import ArchivedMemoryReflectionContext


class MemoryReflectionTask:
    """Bind one closed Business Day to the common Memory Reflection Turn."""

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        session: SessionEngine,
        workspace: WorkspaceEngine,
        archived_context: ArchivedMemoryReflectionContext,
        controller: MemoryReflectionActionController,
        turn: ReflectionTurnEntry,
    ) -> None:
        self._memory = memory
        self._session = session
        self._workspace = workspace
        self._archived_context = archived_context
        self._controller = controller
        self._turn = turn

    def eligible(
        self,
        day: CalendarDay,
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

    async def run(
        self,
        *,
        business_day: CalendarDay,
        target_day: CalendarDay,
        archive: ArchiveProjection | None,
        scope: RunScope,
        request_id: str,
        inbox: TurnInbox | None = None,
    ) -> ReflectionTaskOutcome:
        if target_day >= business_day:
            return _skipped(target_day, "target_day_is_open")
        if archive is None:
            return _skipped(target_day, "archive_missing")
        operations = JoinedOperations()
        completed = False
        try:
            skipped = await operations.run(lambda: self._prepare_source(target_day, archive))
            operations.check_cancelled()
            if skipped is not None:
                return skipped
            outcome = (await self._turn.run(
                (
                    "Maintain daily, entity, concept, fact, and note Memory for the "
                    f"closed Business Day {target_day}. Inspect and reuse existing "
                    "Memory before creating. Write one complete document at a time; "
                    "create redirect targets before retiring sources. Finish with core.answer."
                ),
                business_day=business_day,
                scope=scope,
                request_id=request_id,
                input_source="maintenance.memory",
                inbox=inbox,
            ))
            if outcome.status is not TurnOutcomeStatus.COMPLETED:
                self._controller.abort()
                completed = True
                return ReflectionTaskOutcome.from_turn(
                    ReflectionTaskKind.MEMORY, outcome,
                    target_day=target_day,
                )
            result = ReflectionTaskOutcome.from_turn(
                ReflectionTaskKind.MEMORY, outcome,
                target_day=target_day,
                details=self._controller.finish(),
            )
            completed = True
            return result
        except (MemoryIOError, SessionIOError, WorkspaceIOError) as exc:
            raise ReflectionTaskExecutionError("Memory Reflection task failed") from exc
        finally:
            if not completed:
                self._controller.abort()
            self._archived_context.clear()

    def _prepare_source(self, target_day: CalendarDay, archive: ArchiveProjection) -> ReflectionTaskOutcome | None:
        if not self._session.archive_available(target_day, root=archive.session_root):
            return _skipped(target_day, "session_missing")
        if not self._memory.archived_active_available(target_day, archive.session_root):
            return _skipped(target_day, "active_memory_missing")
        projection = self._session.memory_facts(target_day, root=archive.session_root)
        active = self._memory.validate_archived_active(target_day, archive.session_root)
        if not projection.facts and not active.content.strip():
            return _skipped(target_day, "target_sources_empty")
        workspace = self._workspace.archive_view(target_day, root=archive.workspace_root)
        session_view = self._session.archive_view(target_day, root=archive.session_root)
        self._archived_context.bind(
            target_day=target_day, session=session_view,
            workspace=workspace, active_memory=active,
        )
        self._controller.begin(target_day=target_day)
        return None


def _skipped(day: CalendarDay, reason: str) -> ReflectionTaskOutcome:
    return ReflectionTaskOutcome(
        kind=ReflectionTaskKind.MEMORY,
        status=ReflectionTaskStatus.SKIPPED,
        target_day=day,
        reason=reason,
    )
