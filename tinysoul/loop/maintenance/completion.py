"""Maintenance Turn completion policy."""

from __future__ import annotations

from tinysoul.action import ActionResult, ActionResultStatus
from tinysoul.infra.json import JsonObject

from ..errors import LoopInvariantError

MAINTENANCE_COMPLETION = "maintenance"


class MaintenanceCompletionDetector:
    def detect(self, results: tuple[ActionResult, ...]) -> JsonObject | None:
        completions = tuple(
            result
            for result in results
            if result.action_name == "maintenance.complete"
            and result.status is ActionResultStatus.SUCCESS
        )
        if not completions:
            return None
        if len(completions) != 1:
            raise LoopInvariantError(
                "A Maintenance Turn cycle produced multiple successful completions"
            )
        result = completions[0]
        task = result.payload.get("task")
        if result.payload.get("completed") is not True or task not in {"home", "memory"}:
            raise LoopInvariantError(
                "A successful maintenance.complete result has an invalid payload"
            )
        return {
            "kind": MAINTENANCE_COMPLETION,
            "result_id": result.result_id,
            "task": task,
        }
