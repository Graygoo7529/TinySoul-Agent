"""Cross-module context-pressure recovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from collections.abc import Mapping

from tinysoul.context import ContextEngine, ContextSignalBatch
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import JsonValue
from tinysoul.runtime import RunLevel, RunScope
from tinysoul.workspace import WorkspaceEngine
from tinysoul.workspace.errors import WorkspaceError
from tinysoul.workspace.pressure import WorkspacePressureReclaimer
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
                protected_links=_protected_workspace_links(payload),
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
    model_required = _model_required_chars(payload, target_ratio=target_ratio)
    if model_required is not None:
        return model_required
    if _image_budget_exceeded(payload):
        return 0
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


def _image_budget_exceeded(payload: Mapping[str, JsonValue]) -> bool:
    estimated = _non_negative_int(payload.get("estimated_image_bytes"))
    maximum = _non_negative_int(payload.get("max_image_bytes"), positive=True)
    return estimated is not None and maximum is not None and estimated > maximum


def _model_required_chars(
    payload: Mapping[str, JsonValue],
    *,
    target_ratio: float,
) -> int | None:
    window = _non_negative_int(payload.get("context_window_tokens"), positive=True)
    message_tokens = _non_negative_int(payload.get("estimated_message_tokens"))
    non_message_tokens = _non_negative_int(
        payload.get("estimated_non_message_tokens")
    )
    output_tokens = _non_negative_int(payload.get("reserved_output_tokens"))
    message_chars = _non_negative_int(payload.get("estimated_message_chars"))
    if None in (
        window,
        message_tokens,
        non_message_tokens,
        output_tokens,
        message_chars,
    ):
        return None
    assert window is not None
    assert message_tokens is not None
    assert non_message_tokens is not None
    assert output_tokens is not None
    assert message_chars is not None
    target_total_tokens = int(window * target_ratio)
    target_message_tokens = max(
        0,
        target_total_tokens - non_message_tokens - output_tokens,
    )
    reclaim_tokens = max(0, message_tokens - target_message_tokens)
    if reclaim_tokens <= 0 or message_tokens <= 0 or message_chars <= 0:
        return 1
    return max(
        1,
        (message_chars * reclaim_tokens + message_tokens - 1) // message_tokens,
    )


def _non_negative_int(
    value: JsonValue | None,
    *,
    positive: bool = False,
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or (positive and value <= 0):
        return None
    return value


def _turn_id(scope: RunScope) -> str:
    turn = scope.nearest(RunLevel.TURN)
    return turn.name if turn is not None else ""


def _protected_workspace_links(
    payload: Mapping[str, JsonValue],
) -> frozenset[str]:
    value = payload.get("protected_resource_links", [])
    if not isinstance(value, list):
        return frozenset()
    return frozenset(
        link
        for link in value
        if isinstance(link, str) and link.startswith("workspace:")
    )
