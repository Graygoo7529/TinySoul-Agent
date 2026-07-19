"""Observation helpers for committed Workspace projections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.runtime import (
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RunScope,
    emit_observation,
    observation_enabled,
)

from .manifest import WorkspaceManifest


class WorkspaceChangeOperation(StrEnum):
    """Stable kinds of committed Workspace change."""

    INITIALIZE = "initialize"
    RECONCILE = "reconcile"
    DESCRIBE = "describe"
    WRITE = "write"
    BUNDLE = "bundle"
    PATCH = "patch"
    TRASH = "trash"
    RESTORE = "restore"


@dataclass(frozen=True)
class WorkspaceChange:
    """One final committed Manifest transition."""

    operation: WorkspaceChangeOperation
    before: WorkspaceManifest
    after: WorkspaceManifest

    @property
    def created_links(self) -> tuple[str, ...]:
        before = {record.link for record in self.before.resources}
        return tuple(
            record.link for record in self.after.resources if record.link not in before
        )

    @property
    def removed_links(self) -> tuple[str, ...]:
        after = {record.link for record in self.after.resources}
        return tuple(
            record.link for record in self.before.resources if record.link not in after
        )

    @property
    def updated_links(self) -> tuple[str, ...]:
        before = {record.link: record for record in self.before.resources}
        return tuple(
            record.link
            for record in self.after.resources
            if record.link in before and record != before[record.link]
        )

    @property
    def links(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    *self.created_links,
                    *self.updated_links,
                    *self.removed_links,
                }
            )
        )


def emit_workspace_changed(
    observations: ObservationEmitter,
    *,
    change: WorkspaceChange,
    scope: RunScope | None = None,
    source: str = "workspace.engine",
) -> None:
    """Publish a compact committed-resource invalidation through the Router."""

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
                "previous_revision": change.before.revision,
                "revision": change.after.revision,
            },
        ),
    )
