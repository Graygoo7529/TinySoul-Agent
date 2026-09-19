"""Workspace actions use the same scoped service as SDK and Gateway."""

from __future__ import annotations

from tinysoul.kernel.action import (
    ActionExecution,
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
    ActionTraceProjection,
)
from tinysoul.infra.json import JsonObject


def _success(
    execution: ActionExecution,
    payload: JsonObject,
    *,
    trace_projection: ActionTraceProjection | None = None,
) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
        trace_projection=trace_projection,
    )


def _failed(
    execution: ActionExecution,
    model_feedback: str,
    failure_data: JsonObject,
    *,
    payload: JsonObject | None = None,
    disposition: ActionFailureDisposition = ActionFailureDisposition.CHANGE_REQUEST,
) -> ActionResult:
    reason_value = failure_data.get("reason")
    reason = (
        reason_value
        if isinstance(reason_value, str) and reason_value
        else "workspace_action_failed"
    )
    constraint = {
        key: value
        for key, value in failure_data.items()
        if key not in {"reason", "error_type"}
    }
    diagnostics = (
        {"error_type": failure_data["error_type"]}
        if "error_type" in failure_data
        else {}
    )
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        failure=ActionLocalFailure(
            reason=reason,
            scope="workspace.action",
            disposition=disposition,
            feedback=model_feedback,
            constraint=constraint,
        ),
        payload=payload,
        frame_data=diagnostics,
    )
