"""Workspace integration with the Context projection protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from tinysoul.context import WorkspaceResource, WorkspaceSnapshot, build_workspace_sync_signal
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import RunScope, RuntimeException, Signal

from .engine import WorkspaceEngine
from .errors import WorkspaceError
from .failures import WorkspaceFailureKind
from .manifest import WorkspaceManifest

if TYPE_CHECKING:
    from tinysoul.loop.preparation import TurnPreparationRequest


class WorkspaceRuntimeBridge(Protocol):
    """Runtime mapping surface needed by Turn preparation."""

    def from_workspace_error(self, error: Exception) -> RuntimeException:
        ...

    def from_failure(
        self,
        kind: WorkspaceFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        ...


def workspace_snapshot(manifest: WorkspaceManifest) -> WorkspaceSnapshot:
    """Project a committed Workspace manifest into Context's read model."""

    return WorkspaceSnapshot(
        revision=manifest.revision,
        resources=tuple(
            WorkspaceResource(link=record.link, summary=record.context_summary)
            for record in manifest.resources
        ),
    )


def workspace_snapshot_signal(
    manifest: WorkspaceManifest,
    *,
    call_id: str,
    scope: RunScope,
    source: str,
) -> Signal:
    return build_workspace_sync_signal(
        workspace_snapshot(manifest),
        call_id=call_id,
        scope=scope,
        source=source,
    )


@dataclass(frozen=True)
class WorkspaceTurnPreparationHandler:
    """Reconcile disk and publish its Manifest before a Turn starts work."""

    workspace: WorkspaceEngine
    runtime_bridge: WorkspaceRuntimeBridge

    def prepare(self, request: "TurnPreparationRequest") -> tuple[Signal, ...]:
        try:
            self.workspace.require_day(request.business_day)
            result = self.workspace.reconcile()
        except WorkspaceError as exc:
            raise self.runtime_bridge.from_workspace_error(exc) from exc
        if not result.complete:
            payload: JsonObject = to_json_object(
                {
                    "limit_reached": result.limit_reached,
                    "skipped_count": result.skipped_count,
                    "skip_counts": result.skip_counts(),
                }
            )
            raise self.runtime_bridge.from_failure(
                WorkspaceFailureKind.IO_FAILED,
                message="Workspace reconciliation was incomplete at Turn start.",
                payload=payload,
            )
        return (
            workspace_snapshot_signal(
                result.manifest,
                call_id=f"{request.turn_id}:workspace",
                scope=request.scope,
                source="workspace.turn_prepare",
            ),
        )
