"""Home Reflection task orchestration around a Reflection Turn."""

from __future__ import annotations

from tinysoul.plugins.home import AgentHomeEngine, AgentHomeIOError
from tinysoul.infra.time import CalendarDay
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import RunScope
from tinysoul.kernel.loop.inbox import TurnInbox
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.kernel.loop.turn import TurnExecutionCancelled

from ..errors import ReflectionTaskExecutionError
from ..models import (
    ReflectionTaskKind,
    ReflectionTaskOutcome,
    ReflectionTaskStatus,
)
from ..turn import ReflectionTurnEntry

class HomeReflectionTask:
    """Run deterministic cleanup and an autonomous Turn for remaining Home diffs."""

    def __init__(
        self,
        *,
        home: AgentHomeEngine,
        turn: ReflectionTurnEntry,
    ) -> None:
        self._home = home
        self._turn = turn

    def pending_counts(self) -> tuple[int, int]:
        pending = self._home.review_pending()
        return pending.change_count, pending.skill_memory_count

    async def run(
        self,
        *,
        business_day: CalendarDay,
        scope: RunScope,
        request_id: str,
        inbox: TurnInbox | None = None,
    ) -> ReflectionTaskOutcome:
        operations = JoinedOperations()
        try:
            skipped = await operations.run(self._prepare)
            operations.check_cancelled()
            if skipped is not None:
                return skipped
            outcome = await self._turn.run(
                "Review and resolve every current runtime Home difference.",
                business_day=business_day,
                scope=scope,
                request_id=request_id,
                input_source="maintenance.home",
                inbox=inbox,
            )
            if outcome.status is not TurnOutcomeStatus.COMPLETED:
                return ReflectionTaskOutcome.from_turn(ReflectionTaskKind.HOME, outcome)
            details = await operations.run(self._finish)
            if operations.cancelled:
                raise TurnExecutionCancelled(outcome)
            return ReflectionTaskOutcome.from_turn(
                ReflectionTaskKind.HOME, outcome, details=details,
            )
        except AgentHomeIOError as exc:
            raise ReflectionTaskExecutionError("Home Reflection task failed") from exc

    def _prepare(self) -> ReflectionTaskOutcome | None:
        snapshot = self._home.review_snapshot()
        if not snapshot.pending:
            removed = self._home.remove_resolved_overlay()
            return ReflectionTaskOutcome(
                kind=ReflectionTaskKind.HOME,
                status=ReflectionTaskStatus.SKIPPED,
                reason="no_home_differences",
                details={
                    "copied_cleaned": snapshot.copied_cleaned,
                    "consistent_cleaned": snapshot.consistent_cleaned,
                    "skill_memories_cleared": snapshot.skill_memories_cleared,
                    "runtime_home_removed": removed,
                },
            )

        return None

    def _finish(self) -> JsonObject:
        pending = self._home.review_pending()
        return {
            "remaining_changes": pending.change_count,
            "remaining_skill_reviews": pending.skill_memory_count,
            "runtime_home_removed": self._home.remove_resolved_overlay() if not pending.pending else False,
        }
