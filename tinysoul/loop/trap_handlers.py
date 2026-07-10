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
from .signals import TurnOutput, build_turn_output_signal


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
class EndTurnOrProgramTrapHandler:
    """End the nearest user-visible frame for an unhandled runtime failure."""

    def handle(self, snap: TrapSnap) -> TrapResult:
        turn = snap.scope.nearest(RunLevel.TURN)
        if turn is not None:
            return TrapResult(transfer=RuntimeTransfer.end(turn))
        return TrapResult(
            transfer=RuntimeTransfer.end(_nearest(snap, RunLevel.PROGRAM))
        )


@dataclass(frozen=True)
class ContextCompressionTrapHandler:
    """Compress context trace and retry the current phase when possible."""

    context: ContextEngine

    def handle(self, snap: TrapSnap) -> TrapResult:
        report = self.context.compress()
        if report.changed:
            module = snap.scope.nearest(RunLevel.MODULE)
            if module is not None:
                return TrapResult(transfer=RuntimeTransfer.retry(module))
            phase = snap.scope.nearest(RunLevel.PHASE)
            if phase is not None:
                return TrapResult(transfer=RuntimeTransfer.retry(phase))
        turn = snap.scope.nearest(RunLevel.TURN)
        if turn is not None:
            return TrapResult(transfer=RuntimeTransfer.end(turn))
        return TrapResult(transfer=RuntimeTransfer.end(_nearest(snap, RunLevel.PROGRAM)))


@dataclass(frozen=True)
class TurnOutputTrapHandler:
    """Publish validated Turn output and end the active Turn frame."""

    def handle(self, snap: TrapSnap) -> TrapResult:
        text = snap.payload.get("text")
        result_id = snap.payload.get("result_id")
        references_value = snap.payload.get("references", [])
        if not isinstance(text, str) or not text:
            raise LoopInvariantError("Turn output trap requires non-empty text")
        if not isinstance(result_id, str) or not result_id:
            raise LoopInvariantError("Turn output trap requires non-empty result_id")
        if not isinstance(references_value, list):
            raise LoopInvariantError("Turn output trap references must be a string list")
        references: list[str] = []
        for item in references_value:
            if not isinstance(item, str) or not item:
                raise LoopInvariantError(
                    "Turn output trap references must contain non-empty strings"
                )
            references.append(item)
        output = TurnOutput(
            text=text,
            result_id=result_id,
            references=tuple(references),
            metadata={
                "action": snap.payload.get("action", "core.answer"),
            },
        )
        return TrapResult(
            transfer=RuntimeTransfer.end(_nearest(snap, RunLevel.TURN)),
            signals=(
                build_turn_output_signal(
                    output,
                    scope=snap.scope,
                    source="loop.turn_output_trap",
                ),
            ),
        )


def _nearest(snap: TrapSnap, level: RunLevel) -> RunFrame:
    frame = snap.scope.nearest(level)
    if frame is None:
        raise LoopInvariantError(f"Runtime scope has no {level.value} frame")
    return frame
