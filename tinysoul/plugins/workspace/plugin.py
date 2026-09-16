"""Current Workspace service and explicit read-only archive contributions."""

from collections.abc import Callable
from functools import partial

from tinysoul.kernel.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.kernel.registration import PluginDeclaration, Service
from tinysoul.runtime import SignalBus

from .actions import register_workspace_actions
from .engine import WorkspaceArchiveView, WorkspaceEngine
from .projection import archived_workspace_segment_registration, workspace_segment_registration
from .runtime_bridge import RuntimeWorkspaceBridge


def declare_workspace(
    workspace: WorkspaceEngine, *, bus: SignalBus, llm_action: LLMActionTaskRunner,
    archive_source: Callable[[], WorkspaceArchiveView | None] | None = None,
) -> PluginDeclaration:
    return PluginDeclaration(
        "workspace", services=(Service(WorkspaceEngine, workspace),),
        segments=(workspace_segment_registration(),
                  *((archived_workspace_segment_registration(archive_source),) if archive_source is not None else ())),
        actions=partial(register_workspace_actions, workspace=workspace, bus=bus,
                        llm_action=llm_action, runtime_bridge=RuntimeWorkspaceBridge()),
    )
