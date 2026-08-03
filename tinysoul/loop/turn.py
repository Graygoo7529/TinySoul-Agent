"""Turn runner for one user turn."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Callable, Protocol

from tinysoul.context import (
    ContextEngine,
    ContextTurnCompletion,
    build_trace_phase_note_signal,
)
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.runtime import (
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    RUNTIME_TURN_END,
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeTrap,
    RuntimeTransfer,
    RuntimeTransferAction,
    RuntimeTransferInterrupt,
    Signal,
    SignalBus,
    emit_observation,
    observation_enabled,
)
from tinysoul.runtime.bridge import RuntimeContextBridge, RuntimeLoopBridge

from .config import TurnSettings
from .completion import (
    TurnCompletion,
    TurnCompletionPipeline,
    user_output_from_completion,
)
from .context_signals import ContextSignalConsumer
from .cycle import CycleOutcome, CycleRunner
from tinysoul.maintenance import BusinessDay
from .errors import LoopInvariantError
from .failures import LoopFailureKind
from .outcomes import TurnFailure, TurnOutcomeStatus, failure_from_runtime
from .preparation import TurnPreparationPipeline, TurnPreparationRequest
from .signals import LoopTraceNoteKind, TurnOutput, consume_turn_outputs


@dataclass(frozen=True)
class TurnOutcome:
    """Outcome of one user turn."""

    context_completion: ContextTurnCompletion | None
    business_day: BusinessDay
    status: TurnOutcomeStatus
    output: TurnOutput | None = None
    exhausted: bool = False
    transfer: RuntimeTransfer | None = None
    failure: TurnFailure | None = None
    completion: JsonObject | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.business_day, BusinessDay):
            raise LoopInvariantError("TurnOutcome requires a BusinessDay")
        if not isinstance(self.status, TurnOutcomeStatus):
            raise LoopInvariantError("TurnOutcome requires a TurnOutcomeStatus")
        if self.status is TurnOutcomeStatus.ANSWERED:
            if self.output is None or self.failure is not None or self.exhausted:
                raise LoopInvariantError("Answered TurnOutcome is inconsistent")
        elif self.status is TurnOutcomeStatus.COMPLETED:
            if (
                self.completion is None
                or self.output is not None
                or self.failure is not None
                or self.exhausted
            ):
                raise LoopInvariantError("Completed TurnOutcome is inconsistent")
        elif self.status is TurnOutcomeStatus.EXHAUSTED:
            if self.output is not None or self.failure is not None or not self.exhausted:
                raise LoopInvariantError("Exhausted TurnOutcome is inconsistent")
        elif self.status is TurnOutcomeStatus.FAILED:
            if self.failure is None:
                raise LoopInvariantError("Failed TurnOutcome requires failure details")
        elif self.output is not None or self.failure is not None or self.exhausted:
            raise LoopInvariantError("Stopped TurnOutcome is inconsistent")

    @property
    def answered(self) -> bool:
        return self.status is TurnOutcomeStatus.ANSWERED


@dataclass(frozen=True)
class _TurnBoundary:
    transfer: RuntimeTransfer
    failure: TurnFailure | None = None
    stopped: bool = False


class TurnActivityController(Protocol):
    """Own bounded work that may extend and must be cleaned with one Turn."""

    def allow_additional_cycle(self, turn_id: str) -> bool: ...

    def wait_before_cycle(self, turn_id: str, *, bus: SignalBus) -> None: ...

    def cleanup_turn(self, turn_id: str) -> None: ...


class TurnRunner:
    """Drive cycles until the user turn is answered or stopped."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        bus: SignalBus,
        trap: RuntimeTrap,
        cycle_runner: CycleRunner,
        settings: TurnSettings,
        completion_to_output: Callable[[JsonObject | None], TurnOutput | None] | None = None,
        context_bridge: RuntimeContextBridge | None = None,
        loop_bridge: RuntimeLoopBridge | None = None,
        signal_consumer: ContextSignalConsumer | None = None,
        completion_pipeline: TurnCompletionPipeline | None = None,
        preparation_pipeline: TurnPreparationPipeline | None = None,
        activity_controller: TurnActivityController | None = None,
        observations: ObservationEmitter | None = None,
    ) -> None:
        self._context = context
        self._bus = bus
        self._trap = trap
        self._cycle_runner = cycle_runner
        self._settings = settings
        self._completion_to_output = completion_to_output or user_output_from_completion
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()
        self._signal_consumer = signal_consumer or ContextSignalConsumer(context, bus)
        self._completion_pipeline = completion_pipeline or TurnCompletionPipeline()
        self._preparation_pipeline = preparation_pipeline or TurnPreparationPipeline()
        self._activity_controller = activity_controller
        self._observations = observations or NullObservationEmitter()
        self._active_scope: RunScope | None = None
        self._active_scope_lock = Lock()

    @property
    def active_scope(self) -> RunScope | None:
        """Return one atomic snapshot of the currently accepting Turn scope."""

        with self._active_scope_lock:
            return self._active_scope

    def run(
        self,
        user_input: str,
        *,
        business_day: BusinessDay,
        scope: RunScope,
        request_id: str = "",
        input_source: str = "",
    ) -> TurnOutcome:
        if not isinstance(business_day, BusinessDay):
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("TurnRunner requires a BusinessDay")
            )
        turn_id = ""
        turn_scope = scope.push(RunLevel.TURN, "turn_start")
        output: TurnOutput | None = None
        exhausted = False
        transfer: RuntimeTransfer | None = None
        failure: TurnFailure | None = None
        stopped = False
        completion: JsonObject | None = None
        try:
            try:
                turn_id = self._context.begin_turn(user_input)
            except ContextError as exc:
                raise self._context_bridge.from_context_error(exc) from exc
            turn_scope = scope.push(RunLevel.TURN, turn_id)
            self._set_active_scope(turn_scope)
            self._emit(
                turn_scope,
                "turn.started",
                ObservationLevel.VERBOSE,
                "Turn started.",
                {
                    "turn_id": turn_id,
                    "request_id": request_id,
                    "input_source": input_source,
                },
            )
            preparation = self._run_preparation(
                turn_id=turn_id,
                user_input=user_input,
                business_day=business_day,
                scope=turn_scope,
            )
            if preparation is not None:
                transfer = preparation.transfer
                failure = preparation.failure
                stopped = preparation.stopped
            if transfer is None:
                cycle_index = 1
                while True:
                    if cycle_index > self._settings.max_cycles:
                        controller = self._activity_controller
                        if controller is None or not controller.allow_additional_cycle(
                            turn_id
                        ):
                            exhausted = True
                            self._record_cycle_limit(turn_scope)
                            break
                    if self._activity_controller is not None:
                        self._activity_controller.wait_before_cycle(
                            turn_id,
                            bus=self._bus,
                        )
                    cycle = self._cycle_runner.run(
                        turn_id=turn_id,
                        cycle_index=cycle_index,
                        scope=turn_scope,
                    )
                    if failure is None:
                        failure = cycle.failure
                    stopped = stopped or cycle.stopped
                    if cycle.completion is not None:
                        completion = cycle.completion
                        break
                    if cycle.transfer is not None:
                        transfer = self._consume_cycle_transfer(cycle, turn_scope)
                        if transfer is not None or failure is not None or stopped:
                            break
                        cycle_index += 1
                        continue
                    if failure is not None or stopped:
                        break
                    cycle_index += 1
        except RuntimeException as exc:
            captured = self._capture(exc, turn_scope)
            transfer = captured.transfer
            failure = failure or captured.failure
        finally:
            controller = self._activity_controller
            if controller is not None and turn_id:
                try:
                    controller.cleanup_turn(turn_id)
                except Exception as exc:
                    self._emit(
                        turn_scope,
                        "turn.activity_cleanup_failed",
                        ObservationLevel.NORMAL,
                        "Turn activity cleanup failed.",
                        {
                            "turn_id": turn_id,
                            "error_type": type(exc).__name__,
                        },
                    )
        try:
            output = self._completion_to_output(completion)
            legacy_output = self._consume_turn_output(turn_id)
            if output is None:
                output = legacy_output
            elif legacy_output is not None:
                raise self._loop_bridge.from_loop_error(
                    LoopInvariantError("Turn produced duplicate completion channels")
                )
        except RuntimeException as exc:
            captured = self._capture(exc, turn_scope)
            if transfer is None:
                transfer = captured.transfer
            failure = failure or captured.failure
        if output is not None and self._is_turn_end(transfer, turn_scope):
            transfer = None
        try:
            context_completion, finish_boundary = self._finish_turn(turn_scope)
        finally:
            self._set_active_scope(None)
        if finish_boundary is not None:
            if transfer is None:
                transfer = finish_boundary.transfer
            failure = failure or finish_boundary.failure
        completion_committed = False
        if context_completion is not None:
            try:
                self._completion_pipeline.run(
                    TurnCompletion(
                        context_completion=context_completion,
                        business_day=business_day,
                        output=output,
                        exhausted=exhausted,
                        completion=completion,
                    )
                )
                completion_committed = True
            except RuntimeException as exc:
                captured = self._capture(exc, turn_scope)
                if transfer is None:
                    transfer = captured.transfer
                failure = failure or captured.failure
        status, failure = self._outcome_status(
            output=output,
            completion=completion,
            completion_committed=completion_committed,
            exhausted=exhausted,
            stopped=stopped,
            transfer=transfer,
            failure=failure,
        )
        if status is TurnOutcomeStatus.ANSWERED and output is not None:
            self._emit(
                turn_scope,
                "turn.output",
                ObservationLevel.NORMAL,
                output.text,
                {
                    "turn_id": turn_id,
                    "text": output.text,
                    "result_id": output.result_id,
                    "references": list(output.references),
                    "metadata": output.metadata,
                },
            )
        else:
            self._emit_non_answered(turn_scope, status=status, failure=failure)
        self._emit(
            turn_scope,
            "turn.completed",
            ObservationLevel.VERBOSE,
            "Turn completed.",
            {
                "turn_id": turn_id,
                "answered": status is TurnOutcomeStatus.ANSWERED,
                "status": status.value,
                "completion_committed": completion_committed,
                "exhausted": exhausted,
                "transfer_action": transfer.action.value if transfer is not None else None,
            },
        )
        return TurnOutcome(
            context_completion=context_completion,
            business_day=business_day,
            status=status,
            output=output,
            exhausted=exhausted,
            transfer=transfer,
            failure=failure,
            completion=completion,
        )

    def _run_preparation(
        self,
        *,
        turn_id: str,
        user_input: str,
        business_day: BusinessDay,
        scope: RunScope,
    ) -> _TurnBoundary | None:
        turn_frame = scope.nearest(RunLevel.TURN)
        if turn_frame is None:
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Turn preparation scope has no Turn frame")
            )
        while True:
            try:
                signals = self._preparation_pipeline.prepare(
                    TurnPreparationRequest(
                        turn_id=turn_id,
                        user_input=user_input,
                        business_day=business_day,
                        scope=scope,
                    )
                )
                self._commit_preparation_signals(signals, scope=scope)
                self._context.complete_preparation()
                return None
            except RuntimeTransferInterrupt as interrupt:
                boundary = self._from_interrupt(interrupt)
                transfer = boundary.transfer
            except RuntimeException as exc:
                boundary = self._capture(exc, scope)
                transfer = boundary.transfer

            if transfer.target != turn_frame:
                return boundary
            if transfer.action is RuntimeTransferAction.RETRY:
                continue
            if transfer.action is RuntimeTransferAction.END:
                return boundary
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError(
                    f"Unsupported Turn preparation transfer: {transfer}"
                )
            )

    def _commit_preparation_signals(
        self,
        signals: tuple[Signal, ...],
        *,
        scope: RunScope,
    ) -> None:
        if not signals:
            return
        preparation_results = self._signal_consumer.emit_and_consume(
            signals,
            scope=scope,
        )
        preparation_call_ids = {
            call_id
            for signal in signals
            if isinstance((call_id := signal.payload.get("call_id")), str)
        }
        rejected = tuple(
            result
            for result in preparation_results
            if result.call_id in preparation_call_ids
        )
        if rejected:
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Context rejected a Turn preparation signal"),
                payload=to_json_object(
                    {
                        "results": [
                            {
                                "call_id": result.call_id,
                                "tool_name": result.tool_name,
                                "feedback": result.model_feedback,
                            }
                            for result in rejected
                        ]
                    }
                ),
            )

    def _consume_turn_output(self, turn_id: str) -> TurnOutput | None:
        if not turn_id:
            return None
        matching: list[TurnOutput] = []
        for signal, output in consume_turn_outputs(self._bus):
            frame = signal.scope.nearest(RunLevel.TURN)
            if frame is not None and frame.name == turn_id:
                matching.append(output)
        if len(matching) > 1:
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("A Turn produced multiple output signals")
            )
        return matching[0] if matching else None

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
        self._signal_consumer.emit_and_consume(
            (
                build_trace_phase_note_signal(
                    {
                        "kind": LoopTraceNoteKind.TURN_CYCLE_LIMIT_REACHED.value,
                        "max_cycles": self._settings.max_cycles,
                    },
                    scope=scope,
                    source="loop.turn",
                ),
            ),
            scope=scope,
        )

    def _end_turn(self) -> ContextTurnCompletion | None:
        if not self._context.turn_active:
            return None
        try:
            return self._context.end_turn()
        except ContextError as exc:
            raise self._context_bridge.from_context_error(exc) from exc

    def _finish_turn(
        self,
        scope: RunScope,
    ) -> tuple[ContextTurnCompletion | None, _TurnBoundary | None]:
        try:
            return self._end_turn(), None
        except RuntimeException as exc:
            self._context.abort_turn()
            return None, self._capture(exc, scope)

    def _capture(self, exc: RuntimeException, scope: RunScope) -> _TurnBoundary:
        result = self._trap.capture(exc, scope)
        self._emit(
            scope,
            "runtime.trap",
            ObservationLevel.VERBOSE,
            exc.message,
            {
                "reason": exc.reason,
                "transfer_action": result.transfer.action.value,
                "transfer_target": str(result.transfer.target),
            },
        )
        for signal in result.signals:
            self._bus.emit(signal)
        return _TurnBoundary(
            transfer=result.transfer,
            failure=failure_from_runtime(exc),
        )

    @staticmethod
    def _from_interrupt(interrupt: RuntimeTransferInterrupt) -> _TurnBoundary:
        cause = interrupt.__cause__
        failure = (
            failure_from_runtime(cause)
            if isinstance(cause, RuntimeException)
            else None
        )
        return _TurnBoundary(transfer=interrupt.transfer, failure=failure)

    def _outcome_status(
        self,
        *,
        output: TurnOutput | None,
        completion: JsonObject | None,
        completion_committed: bool,
        exhausted: bool,
        stopped: bool,
        transfer: RuntimeTransfer | None,
        failure: TurnFailure | None,
    ) -> tuple[TurnOutcomeStatus, TurnFailure | None]:
        if output is not None and completion_committed:
            return TurnOutcomeStatus.ANSWERED, None
        if completion is not None and completion_committed:
            return TurnOutcomeStatus.COMPLETED, None
        if failure is not None:
            return TurnOutcomeStatus.FAILED, failure
        if exhausted:
            return TurnOutcomeStatus.EXHAUSTED, None
        if stopped or transfer is not None:
            return TurnOutcomeStatus.STOPPED, None
        return (
            TurnOutcomeStatus.FAILED,
            TurnFailure(
                reason=RUNTIME_TURN_END,
                message="Turn ended without an answer.",
                module="loop",
                kind=LoopFailureKind.INTERNAL_FAILURE.value,
            ),
        )

    def _emit_non_answered(
        self,
        scope: RunScope,
        *,
        status: TurnOutcomeStatus,
        failure: TurnFailure | None,
    ) -> None:
        payload: dict[str, object] = {"status": status.value}
        if failure is not None:
            payload.update(
                {
                    "reason": failure.reason,
                    "module": failure.module,
                    "kind": failure.kind,
                }
            )
        messages = {
            TurnOutcomeStatus.COMPLETED: "Turn completed without a user answer.",
            TurnOutcomeStatus.EXHAUSTED: "Turn exhausted its cycle limit.",
            TurnOutcomeStatus.STOPPED: "Turn stopped before producing an answer.",
            TurnOutcomeStatus.FAILED: (
                failure.message if failure is not None else "Turn failed."
            ),
        }
        self._emit(
            scope,
            f"turn.{status.value}",
            ObservationLevel.NORMAL,
            messages[status],
            payload,
        )

    def _emit(
        self,
        scope: RunScope,
        name: str,
        level: ObservationLevel,
        message: str,
        payload: dict[str, object],
    ) -> None:
        if not observation_enabled(self._observations, level):
            return
        emit_observation(
            self._observations,
            ObservationEvent(
                name=name,
                level=level,
                source="loop.turn",
                scope=scope,
                message=message,
                payload=to_json_object(payload),
            ),
        )

    def _set_active_scope(self, scope: RunScope | None) -> None:
        with self._active_scope_lock:
            self._active_scope = scope

    @staticmethod
    def _is_turn_end(
        transfer: RuntimeTransfer | None,
        turn_scope: RunScope,
    ) -> bool:
        turn = turn_scope.nearest(RunLevel.TURN)
        return (
            transfer is not None
            and turn is not None
            and transfer.action is RuntimeTransferAction.END
            and transfer.target == turn
        )
