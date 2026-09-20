"""Workspace actions use the same scoped service as SDK and Gateway."""

from __future__ import annotations

from tinysoul.kernel.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.kernel.action import (
    ActionEngineBuilder,
    ActionExecution,
    ActionExecutionContext,
    ActionExecutor,
    ActionFailureDisposition,
    ActionLocalFailure,
    ActionResult,
    ActionResultStage,
    ActionTraceProjection,
)
from tinysoul.kernel.context import PromptBlock, PromptReferenceError, TaskPrompt
from tinysoul.infra.concurrency import JoinedOperations
from tinysoul.infra.json import JsonObject, to_json_object
from ..services import WorkspaceService
from ..errors import WorkspaceContractError, WorkspaceError
from ..runtime_bridge import RuntimeWorkspaceBridge
from ..inspection.models import WorkspaceAnalysisBudgetFailure, WorkspaceTextRangeResult
from ..inspection.search import WorkspaceSearchScope, WorkspaceSearchScopeKind
from ..inspection.text import WorkspaceTextPosition
from ..storage.manifest import (
    WorkspaceResourceRecord,
    WorkspaceResourceKind,
    WorkspaceTag,
)
from ..storage.mutations import WorkspaceTextEdit
from ..prompts import WorkspaceAnalysisPromptBuilder, WorkspacePromptReferenceResolver

from .operations import WorkspaceExecutor
from .analysis import WorkspaceAnalyzeExecutor

WORKSPACE_ACTIONS = (
    "workspace.list",
    "workspace.search",
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
    llm_action: LLMActionTaskRunner,
    runtime_bridge: RuntimeWorkspaceBridge | None = None,
) -> ActionEngineBuilder:
    bridge = runtime_bridge or RuntimeWorkspaceBridge()
    executor = WorkspaceExecutor(workspace, llm_action, bridge)
    for name in WORKSPACE_ACTIONS:
        builder.register_executor(
            name,
            (
                executor
                if name != "workspace.analyze"
                else WorkspaceAnalyzeExecutor(
                    workspace=workspace, llm_action=llm_action, runtime_bridge=bridge
                )
            ),
        )
    return builder
