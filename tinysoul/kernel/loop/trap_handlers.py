"""Trap handlers used by the loop assembly layer."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.runtime import (
    RunFrame,
    RunLevel,
    RuntimeTransfer,
    TrapResult,
    TrapSnap,
)
from .errors import LoopInvariantError
from .pressure import PressureRecovery


@dataclass(frozen=True)
class EndFrameTrapHandler:
    """End the nearest runtime frame at the configured level."""

    level: RunLevel

    def handle(self, snap: TrapSnap) -> TrapResult:
        return TrapResult(transfer=RuntimeTransfer.end(_nearest(snap, self.level)))


@dataclass(frozen=True)
class BudgetSuspendTrapHandler:
    """Suspend at the Turn boundary before the next Cycle has started."""

    def handle(self, snap: TrapSnap) -> TrapResult:
        return TrapResult(transfer=RuntimeTransfer.suspend(_nearest(snap, RunLevel.TURN)))


@dataclass(frozen=True)
class RetryCurrentFrameTrapHandler:
    """Retry the current runtime frame."""

    def handle(self, snap: TrapSnap) -> TrapResult:
        current = snap.scope.current()
        if current is None:
            raise LoopInvariantError("Cannot retry an empty runtime scope")
        return TrapResult(transfer=RuntimeTransfer.retry(current))


@dataclass(frozen=True)
class EndTurnOrAgentTrapHandler:
    """End the nearest user-visible frame for an unhandled runtime failure."""

    def handle(self, snap: TrapSnap) -> TrapResult:
        turn = snap.scope.nearest(RunLevel.TURN)
        if turn is not None:
            return TrapResult(transfer=RuntimeTransfer.end(turn))
        return TrapResult(
            transfer=RuntimeTransfer.end(_nearest(snap, RunLevel.AGENT))
        )


@dataclass(frozen=True)
class ContextPressureTrapHandler:
    """Relieve context pressure and retry the narrowest replayable frame."""

    recovery: PressureRecovery

    def handle(self, snap: TrapSnap) -> TrapResult:
        report = self.recovery.recover(payload=snap.payload, scope=snap.scope)
        if report.changed:
            module = snap.scope.nearest(RunLevel.MODULE)
            if module is not None:
                return TrapResult(
                    transfer=RuntimeTransfer.retry(module), signals=report.signals,
                )
            phase = snap.scope.nearest(RunLevel.PHASE)
            if phase is not None:
                return TrapResult(
                    transfer=RuntimeTransfer.retry(phase), signals=report.signals,
                )
        turn = snap.scope.nearest(RunLevel.TURN)
        if turn is not None:
            return TrapResult(transfer=RuntimeTransfer.end(turn), signals=report.signals)
        return TrapResult(
            transfer=RuntimeTransfer.end(_nearest(snap, RunLevel.AGENT)),
            signals=report.signals,
        )

def _nearest(snap: TrapSnap, level: RunLevel) -> RunFrame:
    frame = snap.scope.nearest(level)
    if frame is None:
        raise LoopInvariantError(f"Runtime scope has no {level.value} frame")
    return frame
