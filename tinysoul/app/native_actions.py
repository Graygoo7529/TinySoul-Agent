"""Native actions registered by the app assembly layer."""

from __future__ import annotations

import os
from pathlib import Path

from tinysoul.action.core.call import ActionExecution
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.context.signals import build_working_patch_signal
from tinysoul.context.working import WorkingPatch, WorkspaceResource
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import SignalBus


def core_answer(
    execution: ActionExecution,
    context: ActionExecutionContext,
) -> JsonObject:
    """Return the final answer payload for the current user turn."""

    text = execution.call.params.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    return {"text": text}


def workspace_scan(root: Path, bus: SignalBus):
    """Create the temporary workspace.scan native action."""

    def execute(
        execution: ActionExecution,
        context: ActionExecutionContext,
    ) -> JsonObject:
        resources = _scan_workspace_resources(root)
        signal_bus = context.signal_bus or bus
        if resources:
            signal_bus.emit(
                build_working_patch_signal(
                    WorkingPatch(set_resources=resources),
                    call_id=execution.call.call_id,
                    scope=execution.framework.scope,
                    source="app.workspace_scan",
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


def _scan_workspace_resources(root: Path) -> tuple[WorkspaceResource, ...]:
    skip_dirs = {
        ".agents",
        ".codex",
        ".git",
        ".pytest-local-tmp",
        ".pytest_cache",
        ".test-tmp",
        "__pycache__",
    }
    resources: list[WorkspaceResource] = []
    max_files = 100
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames if name not in skip_dirs and not name.startswith(".")
        ]
        for filename in sorted(filenames):
            if len(resources) >= max_files:
                return tuple(resources)
            path = Path(dirpath) / filename
            try:
                relative = path.relative_to(root).as_posix()
                size = path.stat().st_size
            except OSError:
                continue
            resources.append(
                WorkspaceResource(
                    link=f"workspace:{relative}",
                    summary=f"{path.suffix or 'file'} file, {size} bytes",
                )
            )
    return tuple(resources)
