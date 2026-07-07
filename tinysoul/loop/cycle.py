"""Cycle runner for one TinySoul execution cycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

from tinysoul.context import ContextEngine
from tinysoul.context.errors import ContextError
from tinysoul.runtime import (
    CyclePhase,
    RUNTIME_PROGRAM_END,
    RUNTIME_TURN_END,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeTrap,
    RuntimeTransfer,
    RuntimeTransferAction,
    SignalBus,
)
from tinysoul.runtime.bridge import RuntimeContextBridge, RuntimeLoopBridge

from .errors import LoopContractError, LoopInvariantError
from .phases import Phase1Outcome, Phase1Unit, Phase2Outcome, Phase2Unit, Phase3Outcome, Phase3Unit
from .signals import LoopControlKind, consume_control_requests

T = TypeVar("T")


@dataclass(frozen=True)
class CycleOutcome:
    """Outcome of one execution cycle."""

    cycle_id: str
    answered: bool = False
    transfer: RuntimeTransfer | None = None


@dataclass(frozen=True)
class _PhaseRun:
    value: object | None = None
    transfer: RuntimeTransfer | None = None
    ended: bool = False


class CycleRunner:
    """Run Phase1, Phase2 and Phase3 in order."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        bus: SignalBus,
        trap: RuntimeTrap,
        phase1: Phase1Unit,
        phase2: Phase2Unit,
        phase3: Phase3Unit,
        context_bridge: RuntimeContextBridge | None = None,
        loop_bridge: RuntimeLoopBridge | None = None,
    ) -> None:
        self._context = context
        self._bus = bus
        self._trap = trap
        self._phase1 = phase1
        self._phase2 = phase2
        self._phase3 = phase3
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()

    def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
    ) -> CycleOutcome:
        if cycle_index <= 0:
            raise self._loop_bridge.from_loop_error(
                LoopContractError("cycle_index must be positive")
            )
        cycle_id = f"cycle_{cycle_index}"
        cycle_scope = scope.push(RunLevel.CYCLE, cycle_id)
        boundary = self._boundary(cycle_scope)
        if boundary is not None:
            return CycleOutcome(cycle_id=cycle_id, transfer=boundary)

        phase1_scope = cycle_scope.push(RunLevel.PHASE, CyclePhase.PHASE1.value)
        phase1 = self._run_phase(
            phase1_scope,
            lambda: self._phase1.run(scope=phase1_scope, cycle_id=cycle_id),
        )
        if phase1.transfer is not None:
            return CycleOutcome(cycle_id=cycle_id, transfer=phase1.transfer)
        if phase1.ended:
            return CycleOutcome(cycle_id=cycle_id)
        phase1_outcome = phase1.value
        if not isinstance(phase1_outcome, Phase1Outcome):
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Phase1 returned an invalid outcome")
            )

        boundary = self._boundary(phase1_scope)
        if boundary is not None:
            return CycleOutcome(cycle_id=cycle_id, transfer=boundary)

        phase2_scope = cycle_scope.push(RunLevel.PHASE, CyclePhase.PHASE2.value)
        phase2 = self._run_phase(
            phase2_scope,
            lambda: self._phase2.run(
                selected_domains=phase1_outcome.selected_domains,
                scope=phase2_scope,
                cycle_id=cycle_id,
                turn_id=turn_id,
            ),
        )
        if phase2.transfer is not None:
            return CycleOutcome(cycle_id=cycle_id, transfer=phase2.transfer)
        if phase2.ended:
            return CycleOutcome(cycle_id=cycle_id)
        phase2_outcome = phase2.value
        if not isinstance(phase2_outcome, Phase2Outcome):
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Phase2 returned an invalid outcome")
            )

        boundary = self._boundary(phase2_scope)
        if boundary is not None:
            return CycleOutcome(cycle_id=cycle_id, transfer=boundary)

        phase3_scope = cycle_scope.push(RunLevel.PHASE, CyclePhase.PHASE3.value)
        phase3 = self._run_phase(
            phase3_scope,
            lambda: self._phase3.run(
                normalization=phase2_outcome.normalization,
                scope=phase3_scope,
                cycle_id=cycle_id,
                turn_id=turn_id,
            ),
        )
        if phase3.transfer is not None:
            return CycleOutcome(cycle_id=cycle_id, transfer=phase3.transfer)
        if phase3.ended:
            return CycleOutcome(cycle_id=cycle_id)
        phase3_outcome = phase3.value
        if not isinstance(phase3_outcome, Phase3Outcome):
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Phase3 returned an invalid outcome")
            )

        boundary = self._boundary(phase3_scope)
        if boundary is not None:
            return CycleOutcome(cycle_id=cycle_id, transfer=boundary)
        return CycleOutcome(cycle_id=cycle_id, answered=phase3_outcome.answered)

    def _run_phase(
        self,
        scope: RunScope,
        phase: Callable[[], T],
    ) -> _PhaseRun:
        current = scope.current()
        if current is None:
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Cannot run a phase with an empty scope")
            )
        while True:
            try:
                return _PhaseRun(value=phase())
            except RuntimeException as exc:
                transfer = self._capture(exc, scope)
                if transfer.target != current:
                    return _PhaseRun(transfer=transfer)
                if transfer.action is RuntimeTransferAction.RETRY:
                    continue
                if transfer.action is RuntimeTransferAction.END:
                    return _PhaseRun(ended=True)
                raise self._loop_bridge.from_loop_error(
                    LoopInvariantError(f"Unsupported phase transfer: {transfer}")
                )

    def _boundary(self, scope: RunScope) -> RuntimeTransfer | None:
        try:
            requests = consume_control_requests(self._bus)
        except LoopContractError as exc:
            return self._capture(self._loop_bridge.from_loop_error(exc), scope)
        if requests:
            if any(request.kind is LoopControlKind.EXIT_PROGRAM for request in requests):
                return self._capture(
                    RuntimeException(
                        reason=RUNTIME_PROGRAM_END,
                        message="Program exit requested.",
                        payload={"source": "loop.control"},
                    ),
                    scope,
                )
            if any(request.kind is LoopControlKind.STOP_TURN for request in requests):
                return self._capture(
                    RuntimeException(
                        reason=RUNTIME_TURN_END,
                        message="Turn stop requested.",
                        payload={"source": "loop.control"},
                    ),
                    scope,
                )
        try:
            self._context.consume_signals(self._bus)
            self._context.merge_pending_inputs()
        except ContextError as exc:
            return self._capture(self._context_bridge.from_context_error(exc), scope)
        return None

    def _capture(self, exc: RuntimeException, scope: RunScope) -> RuntimeTransfer:
        result = self._trap.capture(exc, scope)
        for signal in result.signals:
            self._bus.emit(signal)
        return result.transfer
