"""Cycle runner for one TinySoul execution cycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

from tinysoul.context import ContextEngine
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.errors import TaskCancelled
from tinysoul.runtime import (
    CyclePhase,
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RUNTIME_PROGRAM_END,
    RUNTIME_TURN_END,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeTransferInterrupt,
    RuntimeTrap,
    RuntimeTransfer,
    RuntimeTransferAction,
    SignalBus,
    emit_observation,
    observation_enabled,
)
from tinysoul.runtime.bridge import RuntimeContextBridge, RuntimeLoopBridge

from .cancellation import TurnCancellation
from .context_signals import ContextSignalConsumer
from .errors import LoopContractError, LoopInvariantError
from .outcomes import TurnFailure, failure_from_runtime
from .phases import (
    Phase1Outcome,
    Phase1Unit,
    Phase2Outcome,
    Phase2Unit,
    Phase3Outcome,
    Phase3Unit,
    PhaseFailure,
)
from .signals import LoopControlKind, consume_control_signal_requests

T = TypeVar("T")


@dataclass(frozen=True)
class CycleOutcome:
    """Outcome of one execution cycle."""

    cycle_id: str
    transfer: RuntimeTransfer | None = None
    failure: TurnFailure | None = None
    stopped: bool = False
    completion: JsonObject | None = None
    phase_failure: PhaseFailure | None = None


@dataclass(frozen=True)
class _PhaseRun:
    value: object | None = None
    transfer: RuntimeTransfer | None = None
    failure: TurnFailure | None = None
    ended: bool = False
    cancelled: bool = False


@dataclass(frozen=True)
class _CycleBoundary:
    transfer: RuntimeTransfer
    failure: TurnFailure | None = None
    stopped: bool = False


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
        loop_bridge: RuntimeLoopBridge | None = None,
        signal_consumer: ContextSignalConsumer | None = None,
        context_bridge: RuntimeContextBridge | None = None,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._context = context
        self._bus = bus
        self._trap = trap
        self._phase1 = phase1
        self._phase2 = phase2
        self._phase3 = phase3
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._signal_consumer = signal_consumer or ContextSignalConsumer(context, bus)
        self._observations = observations or NullObservationEmitter()

    def run(
        self,
        *,
        turn_id: str,
        cycle_index: int,
        scope: RunScope,
        cancellation: TurnCancellation | None = None,
        phase_feedback: tuple[str, ...] = (),
    ) -> CycleOutcome:
        if cycle_index <= 0:
            raise self._loop_bridge.from_loop_error(
                LoopContractError("cycle_index must be positive")
            )
        cycle_id = f"cycle_{cycle_index}"
        cycle_scope = scope.push(RunLevel.CYCLE, cycle_id)
        boundary = self._boundary(cycle_scope)
        if boundary is not None:
            return CycleOutcome(
                cycle_id=cycle_id,
                transfer=boundary.transfer,
                failure=boundary.failure,
                stopped=boundary.stopped,
            )

        phase1_scope = cycle_scope.push(RunLevel.PHASE, CyclePhase.PHASE1.value)
        self._emit_phase(phase1_scope, CyclePhase.PHASE1, started=True)
        phase1 = self._run_phase(
            phase1_scope,
            lambda: self._phase1.run(
                scope=phase1_scope,
                cycle_id=cycle_id,
                cancellation=cancellation,
                initial_feedback=phase_feedback,
            ),
        )
        self._emit_phase_result(phase1_scope, CyclePhase.PHASE1, phase1)
        if phase1.cancelled:
            return self._cancelled_outcome(cycle_id, phase1_scope, cancellation)
        if phase1.transfer is not None:
            return CycleOutcome(
                cycle_id=cycle_id,
                transfer=phase1.transfer,
                failure=phase1.failure,
            )
        if phase1.ended:
            return CycleOutcome(cycle_id=cycle_id, failure=phase1.failure)
        phase1_outcome = phase1.value
        if not isinstance(phase1_outcome, Phase1Outcome):
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Phase1 returned an invalid outcome")
            )
        if phase1_outcome.failure is not None:
            return CycleOutcome(
                cycle_id=cycle_id,
                phase_failure=phase1_outcome.failure,
            )

        boundary = self._boundary(phase1_scope)
        if boundary is not None:
            return CycleOutcome(
                cycle_id=cycle_id,
                transfer=boundary.transfer,
                failure=boundary.failure,
                stopped=boundary.stopped,
            )

        phase2_scope = cycle_scope.push(RunLevel.PHASE, CyclePhase.PHASE2.value)
        self._emit_phase(phase2_scope, CyclePhase.PHASE2, started=True)
        phase2 = self._run_phase(
            phase2_scope,
            lambda: self._phase2.run(
                selected_domains=phase1_outcome.selected_domains,
                scope=phase2_scope,
                cycle_id=cycle_id,
                turn_id=turn_id,
                cancellation=cancellation,
            ),
        )
        self._emit_phase_result(phase2_scope, CyclePhase.PHASE2, phase2)
        if phase2.cancelled:
            return self._cancelled_outcome(cycle_id, phase2_scope, cancellation)
        if phase2.transfer is not None:
            return CycleOutcome(
                cycle_id=cycle_id,
                transfer=phase2.transfer,
                failure=phase2.failure,
            )
        if phase2.ended:
            return CycleOutcome(cycle_id=cycle_id, failure=phase2.failure)
        phase2_outcome = phase2.value
        if not isinstance(phase2_outcome, Phase2Outcome):
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Phase2 returned an invalid outcome")
            )
        if phase2_outcome.failure is not None:
            return CycleOutcome(
                cycle_id=cycle_id,
                phase_failure=phase2_outcome.failure,
            )

        boundary = self._boundary(phase2_scope)
        if boundary is not None:
            return CycleOutcome(
                cycle_id=cycle_id,
                transfer=boundary.transfer,
                failure=boundary.failure,
                stopped=boundary.stopped,
            )

        phase3_scope = cycle_scope.push(RunLevel.PHASE, CyclePhase.PHASE3.value)
        self._emit_phase(phase3_scope, CyclePhase.PHASE3, started=True)
        phase3 = self._run_phase(
            phase3_scope,
            lambda: self._phase3.run(
                normalization=phase2_outcome.normalization,
                scope=phase3_scope,
                cycle_id=cycle_id,
                turn_id=turn_id,
                cancellation=cancellation,
            ),
        )
        self._emit_phase_result(phase3_scope, CyclePhase.PHASE3, phase3)
        if phase3.cancelled:
            return self._cancelled_outcome(cycle_id, phase3_scope, cancellation)
        if phase3.transfer is not None:
            return CycleOutcome(
                cycle_id=cycle_id,
                transfer=phase3.transfer,
                failure=phase3.failure,
            )
        if phase3.ended:
            return CycleOutcome(cycle_id=cycle_id, failure=phase3.failure)
        phase3_outcome = phase3.value
        if not isinstance(phase3_outcome, Phase3Outcome):
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Phase3 returned an invalid outcome")
            )

        boundary = self._boundary(phase3_scope)
        if boundary is not None:
            return CycleOutcome(
                cycle_id=cycle_id,
                transfer=boundary.transfer,
                failure=boundary.failure,
                stopped=boundary.stopped,
            )
        return CycleOutcome(
            cycle_id=cycle_id,
            completion=phase3_outcome.completion,
        )

    def _emit_phase(
        self,
        scope: RunScope,
        phase: CyclePhase,
        *,
        started: bool,
        payload: JsonObject | None = None,
    ) -> None:
        if not observation_enabled(
            self._observations,
            ObservationLevel.VERBOSE,
        ):
            return
        state = "started" if started else "completed"
        emit_observation(
            self._observations,
            ObservationEvent(
                name=f"loop.phase.{state}",
                level=ObservationLevel.VERBOSE,
                source="loop.cycle",
                scope=scope,
                message=f"{phase.value} {state}.",
                payload={"phase": phase.value, **(payload or {})},
            ),
        )

    def _emit_phase_result(
        self,
        scope: RunScope,
        phase: CyclePhase,
        result: _PhaseRun,
    ) -> None:
        self._emit_phase(
            scope,
            phase,
            started=False,
            payload={
                "ended": result.ended,
                "transfer_action": (
                    result.transfer.action.value
                    if result.transfer is not None
                    else None
                ),
            },
        )

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
            except TaskCancelled:
                # A Turn-level cancel fired while a phase LLM call was in
                # flight. The pending control signal is consumed at the
                # cycle boundary, which stays authoritative for control flow.
                return _PhaseRun(cancelled=True)
            except RuntimeTransferInterrupt as interrupt:
                boundary = self._from_interrupt(interrupt)
                transfer = boundary.transfer
                if transfer.target != current:
                    return _PhaseRun(
                        transfer=transfer,
                        failure=boundary.failure,
                    )
                if transfer.action is RuntimeTransferAction.RETRY:
                    continue
                if transfer.action is RuntimeTransferAction.END:
                    return _PhaseRun(ended=True, failure=boundary.failure)
                raise self._loop_bridge.from_loop_error(
                    LoopInvariantError(f"Unsupported phase transfer: {transfer}")
                )
            except RuntimeException as exc:
                boundary = self._capture(exc, scope)
                transfer = boundary.transfer
                if transfer.target != current:
                    return _PhaseRun(
                        transfer=transfer,
                        failure=boundary.failure,
                    )
                if transfer.action is RuntimeTransferAction.RETRY:
                    continue
                if transfer.action is RuntimeTransferAction.END:
                    return _PhaseRun(ended=True, failure=boundary.failure)
                raise self._loop_bridge.from_loop_error(
                    LoopInvariantError(f"Unsupported phase transfer: {transfer}")
                )

    def _cancelled_outcome(
        self,
        cycle_id: str,
        scope: RunScope,
        cancellation: TurnCancellation | None,
    ) -> CycleOutcome:
        """Converge an in-flight cancel through the boundary control signals."""

        boundary = self._boundary(scope)
        if boundary is None:
            # Defensive: the token fired but no control signal is pending
            # (it may have been consumed by an earlier boundary). Fall back
            # to the recorded control kind.
            kind = cancellation.kind if cancellation is not None else None
            if kind is LoopControlKind.EXIT_PROGRAM:
                boundary = self._capture(
                    RuntimeException(
                        reason=RUNTIME_PROGRAM_END,
                        message="Program exit requested.",
                        payload={"source": "loop.cancel"},
                    ),
                    scope,
                    failure=False,
                )
            else:
                captured = self._capture(
                    RuntimeException(
                        reason=RUNTIME_TURN_END,
                        message="Turn stop requested.",
                        payload={"source": "loop.cancel"},
                    ),
                    scope,
                    failure=False,
                )
                boundary = _CycleBoundary(
                    transfer=captured.transfer,
                    stopped=True,
                )
        return CycleOutcome(
            cycle_id=cycle_id,
            transfer=boundary.transfer,
            failure=boundary.failure,
            stopped=boundary.stopped,
        )

    def _boundary(self, scope: RunScope) -> _CycleBoundary | None:
        try:
            current_turn = scope.nearest(RunLevel.TURN)
            requests = tuple(
                request
                for signal, request in consume_control_signal_requests(self._bus)
                if current_turn is not None
                and signal.scope.nearest(RunLevel.TURN) == current_turn
            )
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
                    failure=False,
                )
            if any(request.kind is LoopControlKind.STOP_TURN for request in requests):
                boundary = self._capture(
                    RuntimeException(
                        reason=RUNTIME_TURN_END,
                        message="Turn stop requested.",
                        payload={"source": "loop.control"},
                    ),
                    scope,
                    failure=False,
                )
                return _CycleBoundary(
                    transfer=boundary.transfer,
                    stopped=True,
                )
        try:
            self._signal_consumer.consume(scope=scope)
            self._context.merge_pending_inputs()
        except RuntimeTransferInterrupt as interrupt:
            return self._from_interrupt(interrupt)
        except RuntimeException as exc:
            return self._capture(exc, scope)
        except ContextError as exc:
            return self._capture(
                self._context_bridge.from_context_error(exc),
                scope,
            )
        return None

    def _capture(
        self,
        exc: RuntimeException,
        scope: RunScope,
        *,
        failure: bool = True,
    ) -> _CycleBoundary:
        result = self._trap.capture(exc, scope)
        for signal in result.signals:
            self._bus.emit(signal)
        return _CycleBoundary(
            transfer=result.transfer,
            failure=failure_from_runtime(exc) if failure else None,
        )

    @staticmethod
    def _from_interrupt(interrupt: RuntimeTransferInterrupt) -> _CycleBoundary:
        cause = interrupt.__cause__
        failure = (
            failure_from_runtime(cause)
            if isinstance(cause, RuntimeException)
            else None
        )
        return _CycleBoundary(transfer=interrupt.transfer, failure=failure)
