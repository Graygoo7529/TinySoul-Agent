"""Workspace action handlers."""

from __future__ import annotations

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext, ActionExecutor
from tinysoul.action.core.result import ActionResult, ActionResultStage
from tinysoul.context.signals import build_working_patch_signal
from tinysoul.context.working import WorkingPatch, WorkspaceResource
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import SignalBus

from .engine import WorkspaceEngine
from .errors import WorkspaceError


def workspace_scan(engine: WorkspaceEngine, bus: SignalBus):
    """Create the workspace.scan native action."""

    def execute(
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> JsonObject:
        scan = engine.scan()
        resources = scan.to_working_resources()
        signal_bus = context.signal_bus or bus
        if resources:
            signal_bus.emit(
                build_working_patch_signal(
                    WorkingPatch(set_resources=resources),
                    call_id=execution.call.call_id,
                    scope=execution.framework.scope,
                    source="workspace.scan",
                )
            )
        return {
            "count": len(resources),
            "resources": [
                {"link": resource.link, "summary": resource.summary}
                for resource in resources
            ],
        }

    return execute


class WorkspaceDescribeExecutor(ActionExecutor):
    """Refresh and return one workspace resource summary."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = execution.call.params.get("link")
        if not isinstance(link, str) or not link:
            return _failed(
                execution,
                "workspace.describe requires a non-empty 'link' parameter.",
                {"reason": "missing_link"},
            )
        try:
            record = self._workspace.describe(link)
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace describe failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        resource = WorkspaceResource(link=record.link, summary=record.summary)
        signal_bus = context.signal_bus or self._bus
        signal_bus.emit(
            build_working_patch_signal(
                WorkingPatch(set_resources=(resource,)),
                call_id=execution.call.call_id,
                scope=execution.framework.scope,
                source="workspace.describe",
            )
        )
        return ActionResult.success(
            call_id=execution.call.call_id,
            invoke_id=execution.framework.invoke_id,
            batch_id=execution.framework.batch_id,
            action_name=execution.call.action_name,
            sequence=execution.call.sequence,
            domain=execution.framework.domain,
            payload={
                "link": record.link,
                "summary": record.summary,
                "size": record.size,
                "mtime": record.mtime,
                "digest": record.digest,
            },
        )


def _failed(
    execution: ActionExecution,
    model_feedback: str,
    frame_data: JsonObject,
) -> ActionResult:
    return ActionResult.failed(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        stage=ActionResultStage.EXECUTE,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        model_feedback=model_feedback,
        frame_data=frame_data,
    )
