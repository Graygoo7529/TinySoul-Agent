"""Cross-module context-pressure recovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from collections.abc import Mapping

from tinysoul.context import ContextEngine, ContextSignalBatch
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import JsonValue
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.workspace import WorkspaceEngine, WorkspacePressureReclaimer
from tinysoul.workspace.errors import WorkspaceError
from tinysoul.workspace.projection import workspace_snapshot_signal


class PressureRecoveryStatus(StrEnum):
    RECOVERED = "recovered"
    NO_PROGRESS = "no_progress"
    FAILED = "failed"


@dataclass(frozen=True)
class PressureRecoveryResult:
    status: PressureRecoveryStatus
    reclaimed_chars: int
    evicted_background_links: tuple[str, ...] = field(default_factory=tuple)
    trashed_refs: tuple[str, ...] = field(default_factory=tuple)
    error: str = ""

    @property
    def changed(self) -> bool:
        return self.status is PressureRecoveryStatus.RECOVERED


class ContextPressureRecovery:
    """Coordinate lossless Context compaction and recoverable Workspace cleanup."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        workspace: WorkspaceEngine,
        target_ratio: float,
    ) -> None:
        self._context = context
        self._workspace = workspace
        self._workspace_reclaimer = WorkspacePressureReclaimer(workspace)
        self._target_ratio = target_ratio

    def recover(
        self,
        *,
        payload: Mapping[str, JsonValue],
        scope: RunScope,
    ) -> PressureRecoveryResult:
        required = _required_chars(payload, target_ratio=self._target_ratio)
        try:
            context_report = self._context.reclaim_pressure(required_chars=required)
            remaining = max(0, required - context_report.reclaimed_chars)
            workspace_report = self._workspace_reclaimer.reclaim(
                required_chars=remaining,
                turn_id=_turn_id(scope),
            )
            if workspace_report.changed:
                signal = workspace_snapshot_signal(
                    self._workspace.snapshot(),
                    call_id="context_pressure",
                    scope=scope,
                    source="loop.context_pressure",
                )
                results = self._context.consume_signal_batch(
                    ContextSignalBatch(turn_id=_turn_id(scope), signals=(signal,))
                )
                if results:
                    rollback_error = ""
                    try:
                        for trash_ref in reversed(workspace_report.trashed_refs):
                            self._workspace.restore_resource(trash_ref)
                    except WorkspaceError as exc:
                        rollback_error = f"; rollback failed: {exc}"
                    return PressureRecoveryResult(
                        status=PressureRecoveryStatus.FAILED,
                        reclaimed_chars=context_report.reclaimed_chars,
                        evicted_background_links=context_report.evicted_background_links,
                        trashed_refs=workspace_report.trashed_refs,
                        error=(
                            "Context rejected the pressure-recovery Workspace snapshot"
                            + rollback_error
                        ),
                    )
            reclaimed = (
                context_report.reclaimed_chars + workspace_report.reclaimed_chars
            )
            if reclaimed <= 0:
                return PressureRecoveryResult(
                    status=PressureRecoveryStatus.NO_PROGRESS,
                    reclaimed_chars=0,
                )
            return PressureRecoveryResult(
                status=PressureRecoveryStatus.RECOVERED,
                reclaimed_chars=reclaimed,
                evicted_background_links=context_report.evicted_background_links,
                trashed_refs=workspace_report.trashed_refs,
            )
        except (ContextError, WorkspaceError) as exc:
            return PressureRecoveryResult(
                status=PressureRecoveryStatus.FAILED,
                reclaimed_chars=0,
                error=str(exc),
            )


def _required_chars(
    payload: Mapping[str, JsonValue],
    *,
    target_ratio: float,
) -> int:
    estimated = payload.get("estimated_chars")
    maximum = payload.get("max_chars")
    if (
        isinstance(estimated, int)
        and not isinstance(estimated, bool)
        and isinstance(maximum, int)
        and not isinstance(maximum, bool)
        and maximum > 0
    ):
        if estimated <= maximum:
            return 0
        target = int(maximum * target_ratio)
        return max(1, estimated - target)
    return 1


def _turn_id(scope: RunScope) -> str:
    turn = scope.nearest(RunLevel.TURN)
    return turn.name if turn is not None else ""
