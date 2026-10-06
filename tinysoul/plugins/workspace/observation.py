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

    if not change.changed:
        return
    if not observation_enabled(observations, ObservationLevel.NORMAL):
        return
    refs = change.refs
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
                "ref": refs[0] if len(refs) == 1 else "",
                "refs": list(refs),
                "created_refs": list(change.created_refs),
                "updated_refs": list(change.updated_refs),
                "removed_refs": list(change.removed_refs),
            },
        ),
    )
