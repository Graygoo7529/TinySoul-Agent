"""Workspace actions use the same scoped service as SDK and Gateway."""

from __future__ import annotations

from tinysoul.kernel.action import ActionEngineBuilder
from tinysoul.kernel.action.tasks import ActionTaskFactory
from tinysoul.kernel.loop.phases import LLMRunner

from ..runtime_bridge import RuntimeWorkspaceBridge
from ..services import WorkspaceService
from .analysis import WorkspaceAnalyzeExecutor
from .operations import WorkspaceExecutor

WORKSPACE_ACTIONS = (
    "workspace.list",
    "workspace.search",
    "workspace.inspect",
    "workspace.read",
    "workspace.write",
    "workspace.edit",
    "workspace.append",
    "workspace.move",
    "workspace.mkdir",
    "workspace.delete",
    "workspace.restore",
    "workspace.trash_list",
    "workspace.tag",
    "workspace.describe",
    "workspace.compose",
    "workspace.analyze",
)


def register_workspace_actions(
    builder: ActionEngineBuilder,
    *,
    workspace: WorkspaceService,
    tasks: ActionTaskFactory,
    llm: LLMRunner,
    runtime_bridge: RuntimeWorkspaceBridge | None = None,
) -> ActionEngineBuilder:
    bridge = runtime_bridge or RuntimeWorkspaceBridge()
    executor = WorkspaceExecutor(workspace, tasks, llm, bridge)
    for name in WORKSPACE_ACTIONS:
        builder.register_executor(
            name,
            (
                executor
                if name != "workspace.analyze"
                else WorkspaceAnalyzeExecutor(
                    workspace=workspace, tasks=tasks, llm=llm, runtime_bridge=bridge
                )
            ),
        )
    return builder
