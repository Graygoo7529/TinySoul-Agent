"""Render action results for model feedback."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import ToolResultMessage
from tinysoul.llm.tools import ToolResultStatus

from .result import ActionPhaseResult, ActionResult, ActionResultStatus


class ActionFeedbackRenderer:
    """Render action results into compact model-visible JSON objects."""

    def render_model_payload(self, result: ActionResult) -> JsonObject:
        """Render the model-visible projection of one action result."""

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

    def render_trace_payload(self, result: ActionResult) -> JsonObject:
        """Render the trace/log projection of one action result."""

        value: JsonObject = {
            "result_id": result.result_id,
            "call_id": result.call_id,
            "action": result.action_name,
            "status": result.status.value,
            "stage": result.stage.value,
            "sequence": result.sequence,
            "domain": result.domain,
            "invoke_id": result.invoke_id,
            "batch_id": result.batch_id,
        }
        if result.model_feedback:
            value["feedback"] = result.model_feedback
        if result.payload:
            value["payload"] = result.payload
        if result.frame_data:
            value["frame_data"] = result.frame_data
        return value

    def render_phase_model_payload(self, result: ActionPhaseResult) -> JsonObject:
        """Render the model-visible projection of one action phase result."""

        value: JsonObject = {
            "phase": result.phase,
            "status": result.status.value,
            "stage": result.stage.value,
        }
        if result.model_feedback:
            value["feedback"] = result.model_feedback
        if result.payload:
            value["payload"] = result.payload
        return value

    def render_phase_trace_payload(self, result: ActionPhaseResult) -> JsonObject:
        """Render the trace/log projection of one action phase result."""

        value: JsonObject = {
            "result_id": result.result_id,
            "phase": result.phase,
            "status": result.status.value,
            "stage": result.stage.value,
            "turn_id": result.turn_id,
            "cycle_id": result.cycle_id,
        }
        if result.model_feedback:
            value["feedback"] = result.model_feedback
        if result.payload:
            value["payload"] = result.payload
        if result.frame_data:
            value["frame_data"] = result.frame_data
        return value

    def to_tool_result_message(self, result: ActionResult) -> ToolResultMessage:
        """Render one action result as a model-side tool result replay message."""

        status = (
            ToolResultStatus.OK
            if result.status is ActionResultStatus.SUCCESS
            else ToolResultStatus.ERROR
        )
        return ToolResultMessage.from_json(
            call_id=result.call_id,
            tool_name=result.action_name,
            value=self.render_model_payload(result),
            status=status,
            label="action_result",
        )

    def render_result(self, result: ActionResult) -> JsonObject:
        """Backward-compatible alias for model payload rendering."""

        return self.render_model_payload(result)

    def render_many(self, results: tuple[ActionResult, ...]) -> tuple[JsonObject, ...]:
        return tuple(self.render_result(result) for result in results)

    def to_tool_result_messages(
        self,
        results: tuple[ActionResult, ...],
    ) -> tuple[ToolResultMessage, ...]:
        """Render action results as model-side tool result replay messages."""

        return tuple(self.to_tool_result_message(result) for result in results)

    def render_phase_many(
        self,
        results: tuple[ActionPhaseResult, ...],
    ) -> tuple[JsonObject, ...]:
        return tuple(self.render_phase_model_payload(result) for result in results)
