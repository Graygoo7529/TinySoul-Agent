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
from .manifest import WorkspaceResourceRecord


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
        skip_counts: JsonObject = {}
        for kind, count in scan.skip_counts().items():
            skip_counts[kind] = count
        return {
            "count": len(resources),
            "resources": [
                {"link": resource.link, "summary": resource.summary}
                for resource in resources
            ],
            "skipped_count": scan.skipped_count,
            "skip_counts": skip_counts,
            "limit_reached": scan.limit_reached,
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


class WorkspaceWriteExecutor(ActionExecutor):
    """Write one workspace text resource and refresh its summary."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = _required_link(execution)
        if link is None:
            return _failed(
                execution,
                "workspace.write requires a non-empty 'link' parameter.",
                {"reason": "missing_link"},
            )
        text = execution.call.params.get("text")
        if not isinstance(text, str):
            return _failed(
                execution,
                "workspace.write requires a 'text' string parameter.",
                {"reason": "invalid_text"},
            )
        overwrite = execution.call.params.get("overwrite", False)
        if not isinstance(overwrite, bool):
            return _failed(
                execution,
                "workspace.write overwrite must be a boolean when provided.",
                {"reason": "invalid_overwrite"},
            )
        try:
            record = self._workspace.write_text(
                link,
                text,
                overwrite=overwrite,
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace write failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_resource_set(
            record,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.write",
        )
        return _success(execution, _record_payload(record))


class WorkspacePatchExecutor(ActionExecutor):
    """Apply an exact text replacement to one workspace resource."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = _required_link(execution)
        if link is None:
            return _failed(
                execution,
                "workspace.patch requires a non-empty 'link' parameter.",
                {"reason": "missing_link"},
            )
        old_text = execution.call.params.get("old_text")
        if not isinstance(old_text, str) or not old_text:
            return _failed(
                execution,
                "workspace.patch requires a non-empty 'old_text' string parameter.",
                {"reason": "invalid_old_text"},
            )
        new_text = execution.call.params.get("new_text")
        if not isinstance(new_text, str):
            return _failed(
                execution,
                "workspace.patch requires a 'new_text' string parameter.",
                {"reason": "invalid_new_text"},
            )
        expected_digest = execution.call.params.get("expected_digest", "")
        if not isinstance(expected_digest, str):
            return _failed(
                execution,
                "workspace.patch expected_digest must be a string when provided.",
                {"reason": "invalid_expected_digest"},
            )
        try:
            record = self._workspace.patch_text(
                link,
                old_text=old_text,
                new_text=new_text,
                expected_digest=expected_digest,
            )
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace patch failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        _emit_resource_set(
            record,
            execution=execution,
            context=context,
            bus=self._bus,
            source="workspace.patch",
        )
        return _success(execution, _record_payload(record))


class WorkspaceDeleteExecutor(ActionExecutor):
    """Delete one workspace resource and remove its working summary."""

    def __init__(self, workspace: WorkspaceEngine, bus: SignalBus) -> None:
        self._workspace = workspace
        self._bus = bus

    def execute(
        self,
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> ActionResult:
        link = _required_link(execution)
        if link is None:
            return _failed(
                execution,
                "workspace.delete requires a non-empty 'link' parameter.",
                {"reason": "missing_link"},
            )
        try:
            record = self._workspace.delete_resource(link)
        except WorkspaceError as exc:
            return _failed(
                execution,
                f"Workspace delete failed: {exc}",
                {"error_type": type(exc).__name__},
            )
        signal_bus = context.signal_bus or self._bus
        signal_bus.emit(
            build_working_patch_signal(
                WorkingPatch(remove_resources=(record.link,)),
                call_id=execution.call.call_id,
                scope=execution.framework.scope,
                source="workspace.delete",
            )
        )
        payload = _record_payload(record)
        payload["deleted"] = True
        return _success(execution, payload)


def _required_link(execution: ActionExecution) -> str | None:
    link = execution.call.params.get("link")
    if not isinstance(link, str) or not link:
        return None
    return link


def _emit_resource_set(
    record: WorkspaceResourceRecord,
    *,
    execution: ActionExecution,
    context: ActionExecutionContext,
    bus: SignalBus,
    source: str,
) -> None:
    signal_bus = context.signal_bus or bus
    resource = WorkspaceResource(link=record.link, summary=record.summary)
    signal_bus.emit(
        build_working_patch_signal(
            WorkingPatch(set_resources=(resource,)),
            call_id=execution.call.call_id,
            scope=execution.framework.scope,
            source=source,
        )
    )


def _record_payload(record: WorkspaceResourceRecord) -> JsonObject:
    return {
        "link": record.link,
        "summary": record.summary,
        "size": record.size,
        "mtime": record.mtime,
        "digest": record.digest,
    }


def _success(execution: ActionExecution, payload: JsonObject) -> ActionResult:
    return ActionResult.success(
        call_id=execution.call.call_id,
        invoke_id=execution.framework.invoke_id,
        batch_id=execution.framework.batch_id,
        action_name=execution.call.action_name,
        sequence=execution.call.sequence,
        domain=execution.framework.domain,
        payload=payload,
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
