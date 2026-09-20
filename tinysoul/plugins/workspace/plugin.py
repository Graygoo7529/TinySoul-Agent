"""Current Workspace service and explicit read-only archive contributions."""

from collections.abc import Callable
from functools import partial

from tinysoul.kernel.action.backends.llm_action import LLMActionTaskRunner
from tinysoul.kernel.loop.interaction.events import TurnEventSubscription
from tinysoul.kernel.registration import PluginDeclaration, Service
from tinysoul.runtime import RunScope, Signal
from tinysoul.runtime.events import EnvironmentEvent, EventFilter
from tinysoul.runtime.sources import RuntimeSource

from .actions import register_workspace_actions
from .engine import WorkspaceArchiveView, WorkspaceEngine
from .events import WORKSPACE_CHANGED, WORKSPACE_OWNER, WORKSPACE_WATCH
from .failures import WorkspaceFailureKind
from .projection import (
    WorkspaceTurnPreparationHandler,
    archived_workspace_segment_registration,
    workspace_refresh_signal,
    workspace_segment_registration,
)
from .runtime_bridge import RuntimeWorkspaceBridge
from .services import WorkspaceService


def _refresh(event: EnvironmentEvent, scope: RunScope) -> tuple[Signal, ...]:
    return (
        workspace_refresh_signal(call_id=event.event_id, scope=scope, source=event.source),
    )


def _unavailable(event: EnvironmentEvent, scope: RunScope) -> tuple[Signal, ...]:
    raise RuntimeWorkspaceBridge().from_failure(
        WorkspaceFailureKind.IO_FAILED,
        message="Workspace discovery could not complete.",
        payload=event.payload,
    )


def declare_workspace(
    workspace: WorkspaceService,
    *,
    llm_action: LLMActionTaskRunner,
    owner: WorkspaceEngine,
    source: RuntimeSource | None = None,
    archive_source: Callable[[], WorkspaceArchiveView | None] | None = None,
) -> PluginDeclaration:
    return PluginDeclaration(
        "workspace",
        services=(Service(WorkspaceService, workspace),),
        segments=(
            workspace_segment_registration(owner),
            *((archived_workspace_segment_registration(archive_source),)
              if archive_source is not None else ()),
        ),
        actions=partial(
            register_workspace_actions,
            workspace=workspace,
            llm_action=llm_action,
            runtime_bridge=RuntimeWorkspaceBridge(),
        ),
        preparation=(WorkspaceTurnPreparationHandler(owner, RuntimeWorkspaceBridge()),),
        events=tuple(
            TurnEventSubscription(
                EventFilter(topic=WORKSPACE_CHANGED, source=name),
                _refresh,
                coalesce=True,
                requires_decision=False,
            )
            for name in (WORKSPACE_OWNER, WORKSPACE_WATCH)
        ) + (
            TurnEventSubscription(
                EventFilter(topic="workspace.unavailable", source=WORKSPACE_WATCH),
                _unavailable,
            ),
        ),
        sources=(source,) if source is not None else (),
    )
