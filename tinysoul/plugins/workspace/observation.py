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

from .events import WorkspaceChange


def emit_workspace_changed(
    observations: ObservationEmitter,
    *,
    change: WorkspaceChange,
    scope: RunScope | None = None,
    source: str = "workspace.engine",
) -> None:
    """Project the same committed change to observation sinks only."""

    if change.before == change.after:
        return
    if not observation_enabled(observations, ObservationLevel.NORMAL):
        return
    links = change.links
    emit_observation(
        observations,
        ObservationEvent(
            name="workspace.changed",
            level=ObservationLevel.NORMAL,
            source=source,
            scope=scope or RunScope(),
            message=f"Workspace {change.operation.value} committed.",
            payload={
                "operation": change.operation.value,
                "day": change.after.day,
                "link": links[0] if len(links) == 1 else "",
                "links": list(links),
                "created_links": list(change.created_links),
                "updated_links": list(change.updated_links),
                "removed_links": list(change.removed_links),
            },
        ),
    )
