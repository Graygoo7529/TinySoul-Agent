"""Observation helpers for committed Workspace projections."""

from __future__ import annotations

from tinysoul.runtime import (
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunScope,
    emit_observation,
    observation_enabled,
)

from .manifest import WorkspaceManifest


def emit_workspace_changed(
    observations: ObservationEmitter,
    *,
    operation: str,
    day: str,
    manifest: WorkspaceManifest,
    link: str,
    scope: RunScope,
    source: str,
) -> None:
    """Publish a compact committed-resource invalidation through the Router."""

    if not observation_enabled(observations, ObservationLevel.NORMAL):
        return
    emit_observation(
        observations,
        ObservationEvent(
            name="workspace.changed",
            level=ObservationLevel.NORMAL,
            source=source,
            scope=scope,
            message=f"Workspace resource {operation} committed.",
            payload={
                "operation": operation,
                "day": day,
                "link": link,
                "revision": manifest.revision,
            },
        ),
    )
