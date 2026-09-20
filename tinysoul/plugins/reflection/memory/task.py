"""Memory Reflection target readiness and Turn orchestration."""

from __future__ import annotations

from tinysoul.infra.time import CalendarDay
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.plugins.memory import (
    ActiveMemoryDocument,
    MemoryEngine,
    MemoryIOError,
    MemoryKind,
)
from tinysoul.runtime import RunScope
from tinysoul.kernel.loop.interaction.inbox import TurnInbox
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.plugins.session import SessionEngine, SessionIOError
from tinysoul.plugins.workspace import WorkspaceEngine, WorkspaceIOError

from tinysoul.plugins.archive import ArchiveProjection
from ..errors import ReflectionTaskExecutionError
from ..models import ReflectionTaskKind, ReflectionTaskOutcome, ReflectionTaskStatus
from ..turn import ReflectionTurnEntry
from tinysoul.plugins.memory.actions import MemoryWriteSession
from .context import MemoryReflectionContext


class MemoryReflectionTask:
    """Bind target-day evidence at preparation, including the current day."""

    def __init__(
        self,
        *,
        memory: MemoryEngine,
        session: SessionEngine,
        workspace: WorkspaceEngine,
        target_context: MemoryReflectionContext,
        controller: MemoryWriteSession,
        turn: ReflectionTurnEntry,
    ) -> None:
        self._memory = memory
        self._session = session
        self._workspace = workspace
        self._target_context = target_context
        self._controller = controller
        self._turn = turn

    def eligible(
        self,
        day: CalendarDay,
        *,
        archive: ArchiveProjection | None,
    ) -> bool:
        daily_exists = self.has_daily(day)
        if archive is None:
            if self._session.active_day != day or self._memory.active_day() != day:
                return daily_exists
            projection = self._session.background_snapshot(day)
            active = self._memory.read_active(day)
            return bool(projection.refs or active.content.strip() or daily_exists)
        session_facts = self._session.archive_available(
            day, root=archive.session_root
        ) and bool(self._session.archive_snapshot(day, root=archive.session_root).refs)
        active_facts = self._memory.archived_active_available(
            day, archive.session_root
        ) and bool(
            self._memory.read_archived_active(day, archive.session_root).content.strip()
        )
        return bool(session_facts or active_facts or daily_exists)

    def daily_days(
        self, *, before: CalendarDay | None = None, limit: int = 64
    ) -> tuple[CalendarDay, ...]:
        days = sorted(
            (
                CalendarDay(link.day)
                for link in self._memory.links(kinds=(MemoryKind.DAILY,))
            ),
            reverse=True,
        )
        return tuple(day for day in days if before is None or day < before)[:limit]

    def has_daily(self, day: CalendarDay) -> bool:
        return self._memory.read_daily(day) is not None

    async def run(
        self,
        *,
        active_day: CalendarDay,
        target_day: CalendarDay,
        archive: ArchiveProjection | None,
        scope: RunScope,
        request_id: str,
        inbox: TurnInbox | None = None,
        instructions: str = "",
    ) -> ReflectionTaskOutcome:
        if target_day > active_day:
            return _skipped(target_day, "target_day_is_future")
        operations = JoinedOperations()
        completed = False
        try:
            skipped = await operations.run(
                lambda: self._prepare_source(
                    target_day, archive, active_day=active_day
                )
            )
            operations.check_cancelled()
            if skipped is not None:
                return skipped
            outcome = await self._turn.run(
                (
                    "Maintain daily, entity, concept, fact, and note Memory for the "
                    f"target day {target_day}. Inspect and recall existing Memory "
                    "before writing. If the target daily exists, read it first, then "
                    "revise, reorganize and supplement it with available evidence. "
                    "If it does not exist, create a complete daily. "
                    "Write one complete document at a time; "
                    "create redirect targets before retiring sources. Finish with core.answer."
                    + (
                        f"\nInstructions for this Reflection: {instructions}"
                        if instructions
                        else ""
                    )
                ),
                active_day=active_day,
                scope=scope,
                request_id=request_id,
                input_source="reflection.memory",
                inbox=inbox,
            )
            if outcome.status is not TurnOutcomeStatus.COMPLETED:
                self._controller.abort()
                completed = True
                return ReflectionTaskOutcome.from_turn(
                    ReflectionTaskKind.MEMORY,
                    outcome,
                    target_day=target_day,
                )
            result = ReflectionTaskOutcome.from_turn(
                ReflectionTaskKind.MEMORY,
                outcome,
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
            self._target_context.clear()

    def _prepare_source(
        self,
        target_day: CalendarDay,
        archive: ArchiveProjection | None,
        *,
        active_day: CalendarDay,
    ) -> ReflectionTaskOutcome | None:
        if not self.eligible(target_day, archive=archive):
            return _skipped(target_day, "target_sources_empty")
        workspace = None
        if target_day == active_day:
            session_view = self._session.snapshot_view(target_day)
            active = self._memory.read_active(target_day)
        else:
            session_view = self._session.empty_view(target_day)
            active = ActiveMemoryDocument(
                day=target_day.value, updated_at=None, content=""
            )
            if archive is not None:
                if self._session.archive_available(
                    target_day, root=archive.session_root
                ):
                    session_view = self._session.archive_view(
                        target_day, root=archive.session_root
                    )
                if self._memory.archived_active_available(
                    target_day, archive.session_root
                ):
                    active = self._memory.read_archived_active(
                        target_day, archive.session_root
                    )
                workspace = self._workspace.archive_view(
                    target_day, root=archive.workspace_root
                )
        self._target_context.bind(
            target_day=target_day,
            session=session_view,
            workspace=workspace,
            active_memory=active,
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
