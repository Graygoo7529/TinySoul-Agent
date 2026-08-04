"""Home Maintenance task orchestration around a Maintenance Turn."""

from __future__ import annotations

from tinysoul.home import AgentHomeEngine, AgentHomeIOError
from tinysoul.infra.time import BusinessDay
from tinysoul.loop import TurnOutcomeStatus
from tinysoul.loop.turn import TurnRunner
from tinysoul.runtime import RunScope

from ..errors import MaintenanceTaskExecutionError
from ..models import (
    MaintenanceTaskKind,
    MaintenanceTaskOutcome,
    MaintenanceTaskStatus,
)
from ..turn_boundary import propagate_outer_turn_transfer, turn_failure_details
from .actions import HomeMaintenanceActionController


class HomeMaintenanceTask:
    """Run deterministic cleanup and an autonomous Turn for remaining Home diffs."""

    def __init__(
        self,
        *,
        home: AgentHomeEngine,
        controller: HomeMaintenanceActionController,
        turn: TurnRunner,
    ) -> None:
        self._home = home
        self._controller = controller
        self._turn = turn

    def pending(self) -> bool:
        return self._home.maintenance_pending().pending

    def pending_counts(self) -> tuple[int, int]:
        pending = self._home.maintenance_pending()
        return pending.change_count, pending.skill_memory_count

    def run(
        self,
        *,
        business_day: BusinessDay,
        scope: RunScope,
        request_id: str,
    ) -> MaintenanceTaskOutcome:
        snapshot = self._home.maintenance_snapshot()
        if not snapshot.pending:
            removed = self._home.finalize_maintenance()
            return MaintenanceTaskOutcome(
                kind=MaintenanceTaskKind.HOME,
                status=MaintenanceTaskStatus.SKIPPED,
                reason="no_home_differences",
                details={
                    "copied_cleaned": snapshot.copied_cleaned,
                    "consistent_cleaned": snapshot.consistent_cleaned,
                    "skill_memories_cleared": snapshot.skill_memories_cleared,
                    "runtime_home_removed": removed,
                },
            )

        completed = False
        try:
            self._controller.begin()
            outcome = self._turn.run(
                "Review and resolve every current runtime Home difference.",
                business_day=business_day,
                scope=scope,
                request_id=request_id,
                input_source="maintenance.home",
            )
            propagate_outer_turn_transfer(outcome)
            if (
                outcome.status is not TurnOutcomeStatus.COMPLETED
                or outcome.completion is None
                or outcome.completion.get("task") != "home"
            ):
                self._controller.abort()
                completed = True
                return MaintenanceTaskOutcome(
                    kind=MaintenanceTaskKind.HOME,
                    status=MaintenanceTaskStatus.FAILED,
                    reason="maintenance_turn_failed",
                    details=turn_failure_details(outcome),
                )
            details = self._controller.finish()
            completed = True
            return MaintenanceTaskOutcome(
                kind=MaintenanceTaskKind.HOME,
                status=MaintenanceTaskStatus.COMPLETED,
                details=details,
            )
        except AgentHomeIOError as exc:
            raise MaintenanceTaskExecutionError("Home Maintenance task failed") from exc
        finally:
            if not completed:
                self._controller.abort()
