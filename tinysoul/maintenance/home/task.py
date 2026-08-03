"""Home Maintenance task orchestration around a Maintenance Turn."""

from __future__ import annotations

from tinysoul.home import AgentHomeEngine
from tinysoul.infra.json import JsonObject
from tinysoul.loop import TurnOutcomeStatus
from tinysoul.loop.turn import TurnRunner
from tinysoul.runtime import RunScope

from ..day import BusinessDay
from ..models import (
    MaintenanceTaskKind,
    MaintenanceTaskOutcome,
    MaintenanceTaskStatus,
)
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

        self._controller.begin()
        try:
            outcome = self._turn.run(
                "Review and resolve every current runtime Home difference.",
                business_day=business_day,
                scope=scope,
                request_id=request_id,
                input_source="maintenance.home",
            )
            if (
                outcome.status is not TurnOutcomeStatus.COMPLETED
                or outcome.completion is None
                or outcome.completion.get("task") != "home"
            ):
                self._controller.abort()
                return MaintenanceTaskOutcome(
                    kind=MaintenanceTaskKind.HOME,
                    status=MaintenanceTaskStatus.FAILED,
                    reason="maintenance_turn_failed",
                    details=_turn_failure(outcome),
                )
            details = self._controller.finish()
            return MaintenanceTaskOutcome(
                kind=MaintenanceTaskKind.HOME,
                status=MaintenanceTaskStatus.COMPLETED,
                details=details,
            )
        except Exception:
            self._controller.abort()
            raise


def _turn_failure(outcome: object) -> JsonObject:
    status = getattr(outcome, "status", None)
    failure = getattr(outcome, "failure", None)
    value: JsonObject = {
        "turn_status": getattr(status, "value", "failed"),
    }
    if failure is not None:
        value.update(
            {
                "failure_kind": failure.kind,
                "failure_module": failure.module,
                "failure_reason": failure.reason,
            }
        )
    return value
