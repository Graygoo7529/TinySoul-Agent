"""Workspace action handlers."""

from __future__ import annotations

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.context.signals import build_working_patch_signal
from tinysoul.context.working import WorkingPatch
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import SignalBus

from .engine import WorkspaceEngine


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
