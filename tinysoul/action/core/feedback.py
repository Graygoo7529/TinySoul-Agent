"""Render action results for model feedback."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject

from .result import ActionResult


class ActionFeedbackRenderer:
    """Render action results into compact model-visible JSON objects."""

    def render_result(self, result: ActionResult) -> JsonObject:
        value: JsonObject = {
            "action": result.action_name,
            "status": result.status.value,
            "stage": result.stage.value,
        }
        if result.model_feedback:
            value["feedback"] = result.model_feedback
        if result.payload:
            value["payload"] = result.payload
        return value

    def render_many(self, results: tuple[ActionResult, ...]) -> tuple[JsonObject, ...]:
        return tuple(self.render_result(result) for result in results)
