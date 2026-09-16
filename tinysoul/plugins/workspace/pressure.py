"""Workspace contribution to context-pressure recovery."""

from __future__ import annotations

from dataclasses import dataclass, field

from .engine import WorkspaceEngine
from .errors import WorkspaceError, WorkspaceIOError
from .manifest import WorkspaceRetention


@dataclass(frozen=True)
class WorkspacePressureReport:
    changed: bool
    reclaimed_chars: int
    trashed_refs: tuple[str, ...] = field(default_factory=tuple)
    removed_links: tuple[str, ...] = field(default_factory=tuple)


class WorkspacePressureReclaimer:
    """Move explicitly reclaimable active resources to recoverable Trash."""

    def __init__(self, workspace: WorkspaceEngine) -> None:
        self._workspace = workspace

    def reclaim(
        self,
        *,
        required_chars: int,
        protected_links: frozenset[str] = frozenset(),
        turn_id: str = "",
    ) -> WorkspacePressureReport:
        if required_chars <= 0:
            return WorkspacePressureReport(changed=False, reclaimed_chars=0)
        candidates = [
            record
            for record in self._workspace.snapshot().resources
            if record.link not in protected_links
            and record.retention
            in {WorkspaceRetention.EPHEMERAL, WorkspaceRetention.TURN}
        ]
        candidates.sort(
            key=lambda record: (
                0 if record.retention is WorkspaceRetention.EPHEMERAL else 1,
                record.mtime_ns,
                record.link,
            )
        )
        reclaimed = 0
        trash_refs: list[str] = []
        removed_links: list[str] = []
        try:
            for record in candidates:
                item = self._workspace.trash_resource(
                    record.link,
                    reason="context_pressure",
                    source_turn_id=turn_id,
                )
                trash_refs.append(item.ref)
                removed_links.append(record.link)
                reclaimed += len(record.link) + len(record.context_summary) + 48
                if reclaimed >= required_chars:
                    break
        except WorkspaceError as exc:
            try:
                for trash_ref in reversed(trash_refs):
                    self._workspace.restore_resource(trash_ref)
            except WorkspaceError as rollback_error:
                raise WorkspaceIOError(
                    "Workspace pressure cleanup failed and rollback also failed: "
                    f"{rollback_error}"
                ) from exc
            raise
        return WorkspacePressureReport(
            changed=bool(trash_refs),
            reclaimed_chars=reclaimed,
            trashed_refs=tuple(trash_refs),
            removed_links=tuple(removed_links),
        )
