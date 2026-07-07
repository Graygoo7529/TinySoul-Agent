"""Turn runner for one user turn."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.context import ContextEngine, TurnSummary, build_trace_phase_note_signal
from tinysoul.context.errors import ContextError
from tinysoul.runtime import (
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeTrap,
    RuntimeTransfer,
    RuntimeTransferAction,
    SignalBus,
)
from tinysoul.runtime.bridge import RuntimeContextBridge, RuntimeLoopBridge

from .config import LoopSettings
from .cycle import CycleOutcome, CycleRunner
from .errors import LoopInvariantError


@dataclass(frozen=True)
class TurnOutcome:
    """Outcome of one user turn."""

    summary: TurnSummary | None
    answered: bool = False
    exhausted: bool = False
    transfer: RuntimeTransfer | None = None


class TurnRunner:
    """Drive cycles until the user turn is answered or stopped."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        bus: SignalBus,
        trap: RuntimeTrap,
        cycle_runner: CycleRunner,
        settings: LoopSettings,
        context_bridge: RuntimeContextBridge | None = None,
        loop_bridge: RuntimeLoopBridge | None = None,
    ) -> None:
        self._context = context
        self._bus = bus
        self._trap = trap
        self._cycle_runner = cycle_runner
        self._settings = settings
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()

    def run(self, user_input: str, *, scope: RunScope) -> TurnOutcome:
        turn_id = ""
        turn_scope = scope.push(RunLevel.TURN, "turn_start")
        answered = False
        exhausted = False
        transfer: RuntimeTransfer | None = None
        try:
            try:
                turn_id = self._context.begin_turn(user_input)
            except ContextError as exc:
                raise self._context_bridge.from_context_error(exc) from exc
            turn_scope = scope.push(RunLevel.TURN, turn_id)
            for cycle_index in range(1, self._settings.max_cycles_per_turn + 1):
                cycle = self._cycle_runner.run(
                    turn_id=turn_id,
                    cycle_index=cycle_index,
                    scope=turn_scope,
                )
                if cycle.transfer is not None:
                    transfer = self._consume_cycle_transfer(cycle, turn_scope)
                    if transfer is not None:
                        break
                    continue
                if cycle.answered:
                    answered = True
                    break
            else:
                exhausted = True
                self._record_cycle_limit(turn_scope)
        except RuntimeException as exc:
            transfer = self._capture(exc, turn_scope)
        summary, finish_transfer = self._finish_turn(turn_scope)
        if finish_transfer is not None and transfer is None:
            transfer = finish_transfer
        return TurnOutcome(
            summary=summary,
            answered=answered,
            exhausted=exhausted,
            transfer=transfer,
        )

    def _consume_cycle_transfer(
        self,
        cycle: CycleOutcome,
        turn_scope: RunScope,
    ) -> RuntimeTransfer | None:
        transfer = cycle.transfer
        if transfer is None:
            return None
        turn_frame = turn_scope.current()
        if turn_frame is None:
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Turn scope has no current frame")
            )
        if transfer.target == turn_frame:
            if transfer.action is RuntimeTransferAction.END:
                return transfer
            if transfer.action is RuntimeTransferAction.RETRY:
                return None
        if transfer.target.level is RunLevel.CYCLE:
            return None
        return transfer

    def _record_cycle_limit(self, scope: RunScope) -> None:
        self._bus.emit(
            build_trace_phase_note_signal(
                {
                    "kind": "turn_cycle_limit_reached",
                    "max_cycles": self._settings.max_cycles_per_turn,
                },
                scope=scope,
                source="loop.turn",
            )
        )
        self._consume_context_signals()

    def _end_turn(self) -> TurnSummary | None:
        if not self._context.turn_active:
            return None
        try:
            return self._context.end_turn()
        except ContextError as exc:
            raise self._context_bridge.from_context_error(exc) from exc

    def _finish_turn(
        self,
        scope: RunScope,
    ) -> tuple[TurnSummary | None, RuntimeTransfer | None]:
        try:
            return self._end_turn(), None
        except RuntimeException as exc:
            self._context.abort_turn()
            return None, self._capture(exc, scope)

    def _capture(self, exc: RuntimeException, scope: RunScope) -> RuntimeTransfer:
        result = self._trap.capture(exc, scope)
        for signal in result.signals:
            self._bus.emit(signal)
        return result.transfer

    def _consume_context_signals(self) -> None:
        try:
            self._context.consume_signals(self._bus)
        except ContextError as exc:
            raise self._context_bridge.from_context_error(exc) from exc
