"""Render Action local results into boundary projections."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import ToolResultMessage
from tinysoul.llm.tools import ToolResultStatus

from .result import ActionPhaseResult, ActionResult, ActionResultStatus


@dataclass(frozen=True)
class RenderedActionResult:
    """Visible and canonical ToolResult forms of one ActionResult."""

    visible_message: ToolResultMessage
    canonical_message: ToolResultMessage
    origin_refs: tuple[str, ...] = ()


class ActionResultRenderer:
    """Project Action results without deriving or changing their semantics."""

    def render_model_payload(
        self,
        result: ActionResult,
        *,
        payload: JsonObject | None = None,
    ) -> JsonObject:
        return result.envelope(payload=payload).to_json()

    def render_trace_payload(self, result: ActionResult) -> JsonObject:
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
        if result.failure is not None:
            value["failure"] = result.failure.to_json()
        if result.payload:
            value["payload"] = result.payload
        if result.frame_data:
            value["frame_data"] = result.frame_data
        return value

    def render_phase_model_payload(self, result: ActionPhaseResult) -> JsonObject:
        return {
            "phase": result.phase.value,
            "status": "failed",
            "stage": result.stage.value,
            "failure": result.failure.to_json(),
        }

    def render_phase_trace_payload(self, result: ActionPhaseResult) -> JsonObject:
        value: JsonObject = {
            "result_id": result.result_id,
            "phase": result.phase.value,
            "status": "failed",
            "stage": result.stage.value,
            "turn_id": result.turn_id,
            "cycle_id": result.cycle_id,
            "failure": result.failure.to_json(),
        }
        if result.frame_data:
            value["frame_data"] = result.frame_data
        return value

    def render_tool_result(self, result: ActionResult) -> RenderedActionResult:
        status = (
            ToolResultStatus.OK
            if result.status is ActionResultStatus.SUCCESS
            else ToolResultStatus.ERROR
        )
        visible = ToolResultMessage.from_json(
            call_id=result.call_id,
            tool_name=result.action_name,
            value=self.render_model_payload(result),
            status=status,
            label="action_result",
        )
        projection = result.trace_projection
        if projection is None:
            return RenderedActionResult(
                visible_message=visible,
                canonical_message=visible,
            )
        canonical = ToolResultMessage.from_json(
            call_id=result.call_id,
            tool_name=result.action_name,
            value=self.render_model_payload(
                result,
                payload=projection.canonical_payload,
            ),
            status=status,
            label="action_result_folded",
        )
        return RenderedActionResult(
            visible_message=visible,
            canonical_message=canonical,
            origin_refs=projection.origin_refs,
        )

    def render_many(
        self,
        results: tuple[ActionResult, ...],
    ) -> tuple[RenderedActionResult, ...]:
        return tuple(self.render_tool_result(result) for result in results)

    def render_phase_many(
        self,
        results: tuple[ActionPhaseResult, ...],
    ) -> tuple[JsonObject, ...]:
        return tuple(self.render_phase_model_payload(result) for result in results)
