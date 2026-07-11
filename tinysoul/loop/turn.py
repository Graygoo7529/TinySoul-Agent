"""Turn runner for one user turn."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from tinysoul.context import ContextEngine, TurnSummary, build_trace_phase_note_signal
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import to_json_object
from tinysoul.runtime import (
    RunLevel,
    RunScope,
    RuntimeException,
    RuntimeTrap,
    RuntimeTransfer,
    RuntimeTransferAction,
    RuntimeTransferInterrupt,
    Signal,
    SignalBus,
)
from tinysoul.runtime.bridge import RuntimeContextBridge, RuntimeLoopBridge

from .config import LoopSettings
from .completion import TurnCompletion, TurnCompletionPipeline
from .context_signals import ContextSignalConsumer
from .cycle import CycleOutcome, CycleRunner
from .errors import LoopInvariantError
from .preparation import TurnPreparationPipeline, TurnPreparationRequest
from .signals import LoopTraceNoteKind, TurnOutput, consume_turn_outputs


@dataclass(frozen=True)
class TurnOutcome:
    """Outcome of one user turn."""

    summary: TurnSummary | None
    output: TurnOutput | None = None
    exhausted: bool = False
    transfer: RuntimeTransfer | None = None

    @property
    def answered(self) -> bool:
        return self.output is not None


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
        signal_consumer: ContextSignalConsumer | None = None,
        completion_pipeline: TurnCompletionPipeline | None = None,
        preparation_pipeline: TurnPreparationPipeline | None = None,
    ) -> None:
        self._context = context
        self._bus = bus
        self._trap = trap
        self._cycle_runner = cycle_runner
        self._settings = settings
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()
        self._signal_consumer = signal_consumer or ContextSignalConsumer(context, bus)
        self._completion_pipeline = completion_pipeline or TurnCompletionPipeline()
        self._preparation_pipeline = preparation_pipeline or TurnPreparationPipeline()
        self._active_scope: RunScope | None = None
        self._active_scope_lock = Lock()

    @property
    def active_scope(self) -> RunScope | None:
        """Return one atomic snapshot of the currently accepting Turn scope."""

        with self._active_scope_lock:
            return self._active_scope

    def run(self, user_input: str, *, scope: RunScope) -> TurnOutcome:
        turn_id = ""
        turn_scope = scope.push(RunLevel.TURN, "turn_start")
        output: TurnOutput | None = None
        exhausted = False
        transfer: RuntimeTransfer | None = None
        try:
            try:
                turn_id = self._context.begin_turn(user_input)
            except ContextError as exc:
                raise self._context_bridge.from_context_error(exc) from exc
            turn_scope = scope.push(RunLevel.TURN, turn_id)
            self._set_active_scope(turn_scope)
            transfer = self._run_preparation(
                turn_id=turn_id,
                user_input=user_input,
                scope=turn_scope,
            )
            if transfer is None:
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
                else:
                    exhausted = True
                    self._record_cycle_limit(turn_scope)
        except RuntimeException as exc:
            transfer = self._capture(exc, turn_scope)
        try:
            output = self._consume_turn_output(turn_id)
        except RuntimeException as exc:
            if transfer is None:
                transfer = self._capture(exc, turn_scope)
        if output is not None and self._is_turn_end(transfer, turn_scope):
            transfer = None
        try:
            summary, finish_transfer = self._finish_turn(turn_scope)
        finally:
            self._set_active_scope(None)
        if finish_transfer is not None and transfer is None:
            transfer = finish_transfer
        if summary is not None:
            try:
                self._completion_pipeline.run(
                    TurnCompletion(
                        summary=summary,
                        output=output,
                        exhausted=exhausted,
                    )
                )
            except RuntimeException as exc:
                if transfer is None:
                    transfer = self._capture(exc, turn_scope)
        return TurnOutcome(
            summary=summary,
            output=output,
            exhausted=exhausted,
            transfer=transfer,
        )

    def _run_preparation(
        self,
        *,
        turn_id: str,
        user_input: str,
        scope: RunScope,
    ) -> RuntimeTransfer | None:
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
                        scope=scope,
                    )
                )
                self._commit_preparation_signals(signals, scope=scope)
                self._context.complete_preparation()
                return None
            except RuntimeTransferInterrupt as interrupt:
                transfer = interrupt.transfer
            except RuntimeException as exc:
                transfer = self._capture(exc, scope)

            if transfer.target != turn_frame:
                return transfer
            if transfer.action is RuntimeTransferAction.RETRY:
                continue
            if transfer.action is RuntimeTransferAction.END:
                return transfer
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
                        "max_cycles": self._settings.max_cycles_per_turn,
                    },
                    scope=scope,
                    source="loop.turn",
                ),
            ),
            scope=scope,
        )

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
