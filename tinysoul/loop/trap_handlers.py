"""Trap handlers used by the loop assembly layer."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.context import ContextEngine
from tinysoul.runtime import (
    RunFrame,
    RunLevel,
    RuntimeTransfer,
    TrapResult,
    TrapSnap,
)

from .errors import LoopInvariantError


@dataclass(frozen=True)
class EndFrameTrapHandler:
    """End the nearest runtime frame at the configured level."""

    level: RunLevel

    def handle(self, snap: TrapSnap) -> TrapResult:
        return TrapResult(transfer=RuntimeTransfer.end(_nearest(snap, self.level)))


@dataclass(frozen=True)
class RetryCurrentFrameTrapHandler:
    """Retry the current runtime frame."""

    def handle(self, snap: TrapSnap) -> TrapResult:
        current = snap.scope.current()
        if current is None:
            raise LoopInvariantError("Cannot retry an empty runtime scope")
        return TrapResult(transfer=RuntimeTransfer.retry(current))


@dataclass(frozen=True)
class ContextCompressionTrapHandler:
    """Compress context trace and retry the current phase when possible."""

    context: ContextEngine

    def handle(self, snap: TrapSnap) -> TrapResult:
        report = self.context.compress()
        if report.changed:
            phase = snap.scope.nearest(RunLevel.PHASE)
            if phase is not None:
                return TrapResult(transfer=RuntimeTransfer.retry(phase))
        turn = snap.scope.nearest(RunLevel.TURN)
        if turn is not None:
            return TrapResult(transfer=RuntimeTransfer.end(turn))
        return TrapResult(transfer=RuntimeTransfer.end(_nearest(snap, RunLevel.PROGRAM)))


def _nearest(snap: TrapSnap, level: RunLevel) -> RunFrame:
    frame = snap.scope.nearest(level)
    if frame is None:
        raise LoopInvariantError(f"Runtime scope has no {level.value} frame")
    return frame
