"""Context pressure changes model projection without moving Workspace files."""

from collections.abc import Mapping
from tinysoul.kernel.context import ContextEngine
from tinysoul.kernel.context.errors import ContextError
from tinysoul.infra.json import JsonValue
from tinysoul.runtime import RunScope
from tinysoul.kernel.loop.pressure import (
    PressureRecoveryResult,
    PressureRecoveryStatus,
    required_chars,
)


class UserContextPressureRecovery:
    def __init__(self, *, context: ContextEngine, target_ratio: float) -> None:
        self._context, self._target_ratio = context, target_ratio

    def recover(
        self, *, payload: Mapping[str, JsonValue], scope: RunScope
    ) -> PressureRecoveryResult:
        try:
            report = self._context.reclaim_pressure(
                required_chars=required_chars(payload, target_ratio=self._target_ratio)
            )
        except ContextError:
            return PressureRecoveryResult(
                PressureRecoveryStatus.FAILED,
                0,
                error="Context pressure recovery failed.",
            )
        return PressureRecoveryResult(
            (
                PressureRecoveryStatus.RECOVERED
                if report.reclaimed_chars > 0
                else PressureRecoveryStatus.NO_PROGRESS
            ),
            report.reclaimed_chars,
            evicted_background_links=report.evicted_background_links,
        )
