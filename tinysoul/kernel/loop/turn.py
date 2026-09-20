"""Owner-neutral runner for one Agent Turn."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Protocol

from tinysoul.kernel.context import (
    ContextEngine,
    ContextTurnCompletion,
    ContextSignalBatch,
    build_trace_phase_note_signal,
    build_input_append_signal,
)
from tinysoul.kernel.context.errors import ContextError
from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.infra.time import CalendarDay
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
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.kernel.loop.runtime_bridge import RuntimeLoopBridge

from .interaction.cancellation import TurnCancellation
from .config import TurnSettings
from .lifecycle.completion import TurnCompletion, TurnCompletionPipeline
from .context_signals import ContextSignalConsumer
from .cycle import CycleOutcome, CycleRunner
from .errors import LoopInvariantError
from .interaction.inbox import (
    InboxKind,
    TurnInbox,
    TurnState,
    WaitCondition,
    WaitReason,
    WakeReason,
)
from .failures import LOOP_BUDGET_REQUIRED, LoopFailureKind
from .outcomes import TurnFailure, TurnOutcomeStatus, TurnOutput, failure_from_runtime
from .lifecycle.preparation import TurnPreparationPipeline, TurnPreparationRequest
from .signals import LoopControlKind, LoopTraceNoteKind


@dataclass(frozen=True)
class TurnOutcome:
    """Outcome of one reusable Turn execution."""

    context_completion: ContextTurnCompletion | None
    active_day: CalendarDay
    status: TurnOutcomeStatus
    output: TurnOutput | None = None
    exhausted: bool = False
    transfer: RuntimeTransfer | None = None
    failure: TurnFailure | None = None
    completion: JsonObject | None = None
    finish_failures: tuple[TurnFailure, ...] = ()
    cleanup_diagnostics: tuple[CleanupDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.active_day, CalendarDay):
            raise LoopInvariantError("TurnOutcome requires a CalendarDay")
        if not isinstance(self.status, TurnOutcomeStatus):
            raise LoopInvariantError("TurnOutcome requires a TurnOutcomeStatus")
        if any(not isinstance(item, TurnFailure) for item in self.finish_failures):
            raise LoopInvariantError("TurnOutcome requires typed finish failures")
        if any(
            not isinstance(item, CleanupDiagnostic) for item in self.cleanup_diagnostics
        ):
            raise LoopInvariantError("TurnOutcome requires typed cleanup diagnostics")
        if self.finish_failures and self.status is not TurnOutcomeStatus.FAILED:
            raise LoopInvariantError("Required finish failure prevents Turn success")
        if self.status is TurnOutcomeStatus.ANSWERED:
            if self.output is None or self.failure is not None or self.exhausted:
                raise LoopInvariantError("Answered TurnOutcome is inconsistent")
        elif self.status in {
            TurnOutcomeStatus.COMPLETED,
            TurnOutcomeStatus.AWAITING_USER,
        }:
            if (
                self.completion is None
                or self.output is not None
                or self.failure is not None
                or self.exhausted
            ):
                raise LoopInvariantError("Completed TurnOutcome is inconsistent")
        elif self.status is TurnOutcomeStatus.EXHAUSTED:
            if (
                self.output is not None
                or self.failure is not None
                or not self.exhausted
            ):
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


class TurnExecutionCancelled(asyncio.CancelledError):
    """Propagate cancellation while preserving the sealed owner result."""

    def __init__(self, outcome: TurnOutcome) -> None:
        super().__init__("Turn execution was cancelled after finalization")
        self.outcome = outcome


class TurnActivityController(Protocol):
    """Own work that must be cleaned with one Turn; never grant Cycle budget."""

    def bind_inbox(self, turn_id: str, inbox: TurnInbox | None) -> None: ...

    def sync(self, turn_id: str, *, bus: SignalBus, scope: RunScope) -> None: ...

    def has_unresolved(self, turn_id: str) -> bool: ...

    async def cleanup_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]: ...


class TurnRunner:
    """Reusable Turn kernel that drives Cycles until profile completion."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        bus: SignalBus,
        trap: RuntimeTrap,
        cycle_runner: CycleRunner,
        settings: TurnSettings,
        completion_to_output: (
            Callable[[JsonObject | None], TurnOutput | None] | None
        ) = None,
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
        self._completion_to_output = completion_to_output or _no_turn_output
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()
        self._signal_consumer = signal_consumer or ContextSignalConsumer(context, bus)
        self._completion_pipeline = completion_pipeline or TurnCompletionPipeline()
        self._preparation_pipeline = preparation_pipeline or TurnPreparationPipeline()
        self._activity_controller = activity_controller
        self._observations = observations or NullObservationEmitter()
        self._active_scope: RunScope | None = None
        self._active_cancellation: TurnCancellation | None = None
        self._active_scope_lock = Lock()

    async def _consume_inbox(self, inbox: TurnInbox | None, scope: RunScope) -> bool:
        if inbox is None:
            return False
        batch = await inbox.capture()
        signals: list[Signal] = []
        for sequence, record in batch.records:
            if record.kind in {InboxKind.INPUT, InboxKind.REPLY}:
                text = record.payload.get("text")
                if not isinstance(text, str):
                    raise LoopInvariantError("Accepted input has no text")
                reply_to = record.payload.get("reply_to", "")
                if not isinstance(reply_to, str):
                    raise LoopInvariantError("Accepted reply has no question identity")
                signals.append(
                    build_input_append_signal(
                        text,
                        scope=scope,
                        source="loop.inbox",
                        input_id=record.record_id,
                        reply_to=reply_to,
                        admission_sequence=sequence,
                        received_at=record.received_at,
                    )
                )
                continue
            else:
                note = to_json_object(
                    {
                        "kind": "environment_event",
                        "event_id": record.record_id,
                        "event_kind": record.kind.value,
                        "payload": record.payload,
                    }
                )
            signals.append(
                build_trace_phase_note_signal(
                    note, scope=scope, source="loop.inbox", admission_sequence=sequence,
                )
            )
        if signals:
            frame = scope.nearest(RunLevel.TURN)
            if frame is None:
                raise LoopInvariantError("Inbox consumption requires a Turn frame")
            results = await self._signal_consumer.consume_batch(
                ContextSignalBatch(turn_id=frame.name, signals=tuple(signals)),
                scope=scope,
            )
            if results:
                raise LoopInvariantError("Context rejected an accepted Inbox batch")
        await inbox.ack(batch)
        return bool(batch.records)

    @property
    def active_scope(self) -> RunScope | None:
        """Return one atomic snapshot of the currently accepting Turn scope."""

        with self._active_scope_lock:
            return self._active_scope

    def request_active_cancel(self, kind: LoopControlKind) -> bool:
        """Fire the active Turn's cooperative cancel token, if one exists."""

        with self._active_scope_lock:
            cancellation = self._active_cancellation
        if cancellation is None:
            return False
        cancellation.request(kind)
        return True

    async def run(
        self,
        turn_input: str,
        *,
        active_day: CalendarDay,
        scope: RunScope,
        request_id: str = "",
        input_source: str = "",
        inbox: TurnInbox | None = None,
    ) -> TurnOutcome:
        if not isinstance(active_day, CalendarDay):
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("TurnRunner requires a CalendarDay")
            )
        turn_id = ""
        turn_scope = scope.push(RunLevel.TURN, "turn_start")
        output: TurnOutput | None = None
        exhausted = False
        transfer: RuntimeTransfer | None = None
        failure: TurnFailure | None = None
        stopped = False
        completion: JsonObject | None = None
        task_cancellation: asyncio.CancelledError | None = None
        cleanup_diagnostics: list[CleanupDiagnostic] = []
        finish_failures: tuple[TurnFailure, ...] = ()
        try:
            try:
                turn_id = (
                    self._context.begin_turn(turn_input, turn_id=request_id)
                    if request_id
                    else self._context.begin_turn(turn_input)
                )
            except ContextError as exc:
                raise self._context_bridge.from_context_error(exc) from exc
            turn_scope = scope.push(RunLevel.TURN, turn_id)
            if self._activity_controller is not None:
                self._activity_controller.bind_inbox(turn_id, inbox)
            cancellation = TurnCancellation()
            self._set_active_scope(turn_scope, cancellation)
            self._emit(
                turn_scope,
                "turn.started",
                ObservationLevel.VERBOSE,
                "Turn started.",
                {
                    "turn_id": turn_id,
                    "request_id": request_id,
                    "input_source": input_source,
                    "active_day": str(active_day),
                },
            )
            preparation = await self._run_preparation(
                turn_id=turn_id,
                turn_input=turn_input,
                active_day=active_day,
                scope=turn_scope,
            )
            if preparation is not None:
                transfer = preparation.transfer
                failure = preparation.failure
                stopped = preparation.stopped
            if transfer is None:
                if inbox is not None:
                    inbox.set_activity(TurnState.RUNNING)
                cycle_index = 1
                cycle_limit = self._settings.max_cycles
                phase_feedback: list[str] = []
                pending_wait: WaitCondition | None = None
                job_ready = False
                while True:
                    request = None
                    if cycle_index > cycle_limit:
                        if inbox is None:
                            exhausted = True
                            (await self._record_cycle_limit(turn_scope))
                            break
                        request = await inbox.request_budget(cycle_index)
                        suspension = self._trap.capture(
                            RuntimeException(
                                reason=LOOP_BUDGET_REQUIRED,
                                message="Turn requires a Cycle budget decision.",
                                payload={
                                    "module": "loop",
                                    "request_id": request.request_id,
                                },
                            ),
                            turn_scope,
                        )
                        if (
                            suspension.transfer.action
                            is not RuntimeTransferAction.SUSPEND
                            or suspension.transfer.target != turn_scope.current()
                        ):
                            raise LoopInvariantError(
                                "Budget Trap must suspend the current Turn"
                            )
                        await self._signal_consumer.consume_recovery(
                            suspension.signals, turn_scope
                        )
                        self._emit(
                            turn_scope,
                            "turn.budget_requested",
                            ObservationLevel.NORMAL,
                            "Turn is waiting for a Cycle budget decision.",
                            {
                                "request_id": request.request_id,
                                "next_cycle_index": cycle_index,
                            },
                        )
                    if inbox is not None and (
                        pending_wait is not None or request is not None
                    ):
                        readiness = await inbox.wait_for_cycle(
                            pending_wait, budget=request, job_ready=job_ready
                        )
                        cycle_limit += readiness.granted_cycles
                        if pending_wait is not None:
                            question = pending_wait.question
                            if (
                                question is not None
                                and readiness.reason is WakeReason.TIMER
                            ):
                                completion = {
                                    "kind": "awaiting_user",
                                    "question_id": question.question_id,
                                }
                                break
                            await self._signal_consumer.emit_and_consume(
                                (
                                    build_trace_phase_note_signal(
                                        {
                                            "kind": "wait_resumed",
                                            "reason": (
                                                readiness.reason.value
                                                if readiness.reason
                                                else None
                                            ),
                                            "sequence": readiness.sequence,
                                            "unanswered_question_id": (
                                                question.question_id
                                                if question is not None
                                                and readiness.reason is WakeReason.INPUT
                                                else None
                                            ),
                                        },
                                        scope=turn_scope,
                                        source="loop.wait",
                                    ),
                                ),
                                scope=turn_scope,
                            )
                        pending_wait = None
                        job_ready = False
                    await self._consume_inbox(inbox, turn_scope)
                    if self._activity_controller is not None:
                        self._activity_controller.sync(
                            turn_id, bus=self._bus, scope=turn_scope
                        )
                    cycle_cursor = (
                        inbox.acknowledged_sequence if inbox is not None else 0
                    )
                    cycle = await self._cycle_runner.run(
                        turn_id=turn_id,
                        cycle_index=cycle_index,
                        scope=turn_scope,
                        cancellation=cancellation,
                        phase_feedback=tuple(phase_feedback),
                    )
                    if failure is None:
                        failure = cycle.failure
                    stopped = stopped or cycle.stopped
                    if cycle.phase_failure is not None:
                        prefix = (
                            f"Previous cycle {cycle.phase_failure.phase.value} "
                            f"failure ({cycle.phase_failure.reason}): "
                        )
                        for item in cycle.phase_failure.feedback:
                            feedback = prefix + item
                            if feedback not in phase_feedback:
                                phase_feedback.append(feedback)
                        cycle_index += 1
                        continue
                    phase_feedback.clear()
                    if cycle.question is not None:
                        question = cycle.question
                        if inbox is not None:
                            await inbox.open_question(question)
                        self._emit(
                            turn_scope,
                            "turn.question",
                            ObservationLevel.NORMAL,
                            question.text,
                            {
                                "question_id": question.question_id,
                                "options": list(question.options),
                            },
                        )
                        if inbox is None:
                            completion = {
                                "kind": "awaiting_user",
                                "question_id": question.question_id,
                            }
                            break
                        pending_wait = WaitCondition(
                            WaitReason.INPUT,
                            cycle_cursor,
                            (
                                asyncio.get_running_loop().time()
                                + question.timeout_seconds
                                if question.timeout_seconds is not None
                                else None
                            ),
                            question=question,
                        )
                        cycle_index += 1
                        continue
                    if cycle.wait is not None:
                        if inbox is None:
                            raise LoopInvariantError(
                                "Wait action requires a Turn Inbox"
                            )
                        pending_wait = cycle.wait.condition(cycle_cursor)
                        job_ready = cycle.wait.ready
                        cycle_index += 1
                        continue
                    if cycle.completion is not None:
                        if (
                            self._activity_controller is not None
                            and self._activity_controller.has_unresolved(turn_id)
                        ):
                            phase_feedback.append(
                                "Resolve the active Jobs before completing this Turn."
                            )
                            cycle_index += 1
                            continue
                        if await self._consume_inbox(inbox, turn_scope):
                            cycle_index += 1
                            continue
                        if inbox is not None:
                            if not await inbox.close_if_empty():
                                cycle_index += 1
                                continue
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
        except asyncio.CancelledError as exc:
            task_cancellation = exc
            stopped = True
            completion = None
        except RuntimeTransferInterrupt as interrupt:
            captured = self._from_interrupt(interrupt)
            transfer = captured.transfer
            failure = failure or captured.failure
        except RuntimeException as exc:
            captured = self._capture(exc, turn_scope)
            transfer = captured.transfer
            failure = failure or captured.failure
        except Exception as exc:
            captured = self._capture(
                self._loop_bridge.from_exception(
                    LoopFailureKind.INTERNAL_FAILURE,
                    exc,
                ),
                turn_scope,
            )
            transfer = captured.transfer
            failure = failure or captured.failure
        finally:
            if inbox is not None:
                inbox.set_activity(TurnState.FINALIZING)

                async def close_ingress() -> None:
                    await inbox.close()

                ingress_closer = asyncio.create_task(close_ingress())
                while not ingress_closer.done():
                    try:
                        await asyncio.shield(ingress_closer)
                    except asyncio.CancelledError as exc:
                        task_cancellation = task_cancellation or exc
                    except Exception:
                        break  # Classify the owned task's failure below.
                try:
                    ingress_closer.result()
                except RuntimeTransferInterrupt as interrupt:
                    captured = self._from_interrupt(interrupt)
                    transfer = transfer or captured.transfer
                    failure = failure or captured.failure
                except RuntimeException as exc:
                    captured = self._capture(exc, turn_scope)
                    transfer = transfer or captured.transfer
                    failure = failure or captured.failure
                except Exception as exc:
                    captured = self._capture(
                        self._loop_bridge.from_exception(
                            LoopFailureKind.INTERNAL_FAILURE,
                            exc,
                        ),
                        turn_scope,
                    )
                    transfer = transfer or captured.transfer
                    failure = failure or captured.failure
            controller = self._activity_controller
            if controller is not None and turn_id:
                try:
                    activity_closer = asyncio.create_task(
                        controller.cleanup_turn(turn_id)
                    )
                    while not activity_closer.done():
                        try:
                            await asyncio.shield(activity_closer)
                        except asyncio.CancelledError as exc:
                            task_cancellation = task_cancellation or exc
                        except Exception:
                            break
                    cleanup_diagnostics.extend(activity_closer.result())
                except (RuntimeException, RuntimeTransferInterrupt) as exc:
                    captured = (
                        self._from_interrupt(exc)
                        if isinstance(exc, RuntimeTransferInterrupt)
                        else self._capture(exc, turn_scope)
                    )
                    if transfer is None or (
                        captured.transfer is not None
                        and captured.transfer.target.level is RunLevel.AGENT
                    ):
                        transfer = captured.transfer
                    if captured.failure is not None:
                        finish_failures = (*finish_failures, captured.failure)
                except Exception as exc:
                    captured = self._capture(
                        self._loop_bridge.from_exception(
                            LoopFailureKind.CONTRACT_VIOLATION,
                            exc,
                        ),
                        turn_scope,
                    )
                    transfer = transfer or captured.transfer
                    if captured.failure is not None:
                        finish_failures = (*finish_failures, captured.failure)
            if (
                inbox is not None or controller is not None
            ) and self._context.turn_active:

                async def drain_final_records() -> None:
                    if controller is not None:
                        controller.sync(turn_id, bus=self._bus, scope=turn_scope)
                    if inbox is not None:
                        while await self._consume_inbox(inbox, turn_scope):
                            pass
                    await self._signal_consumer.consume(scope=turn_scope)

                final_records = asyncio.create_task(drain_final_records())
                while not final_records.done():
                    try:
                        await asyncio.shield(final_records)
                    except asyncio.CancelledError as exc:
                        task_cancellation = task_cancellation or exc
                    except Exception:
                        break  # Preserve the original failure for the Loop bridge.
                try:
                    final_records.result()
                except RuntimeException as exc:
                    captured = self._capture(exc, turn_scope)
                    failure = failure or captured.failure
                    transfer = transfer or captured.transfer
                except RuntimeTransferInterrupt as interrupt:
                    captured = self._from_interrupt(interrupt)
                    failure = failure or captured.failure
                    transfer = transfer or captured.transfer
                except Exception as exc:
                    captured = self._capture(
                        self._loop_bridge.from_exception(
                            LoopFailureKind.INTERNAL_FAILURE, exc
                        ),
                        turn_scope,
                    )
                    failure = failure or captured.failure
                    transfer = transfer or captured.transfer
        try:
            output = self._completion_to_output(completion)
            if output is not None and not isinstance(output, TurnOutput):
                output = None
                raise LoopInvariantError("Turn output mapper returned an invalid value")
        except RuntimeTransferInterrupt as interrupt:
            captured = self._from_interrupt(interrupt)
            transfer = transfer or captured.transfer
            failure = failure or captured.failure
        except RuntimeException as exc:
            captured = self._capture(exc, turn_scope)
            if transfer is None:
                transfer = captured.transfer
            failure = failure or captured.failure
        except Exception as exc:
            captured = self._capture(
                self._loop_bridge.from_exception(
                    LoopFailureKind.INTERNAL_FAILURE,
                    exc,
                ),
                turn_scope,
            )
            transfer = transfer or captured.transfer
            failure = failure or captured.failure
        if output is not None and self._is_turn_end(transfer, turn_scope):
            transfer = None
        try:
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
                execution_status, failure = self._outcome_status(
                    output=output,
                    completion=completion,
                    completion_committed=True,
                    exhausted=exhausted,
                    stopped=stopped,
                    transfer=transfer,
                    failure=failure,
                )
                if (
                    task_cancellation is not None
                    and execution_status is TurnOutcomeStatus.STOPPED
                ):
                    execution_status = TurnOutcomeStatus.CANCELLED

                def capture_finish_failure(
                    exc: RuntimeException | RuntimeTransferInterrupt,
                ) -> TurnFailure:
                    nonlocal transfer
                    captured = (
                        self._from_interrupt(exc)
                        if isinstance(exc, RuntimeTransferInterrupt)
                        else self._capture(exc, turn_scope)
                    )
                    if transfer is None:
                        transfer = captured.transfer
                    return captured.failure or TurnFailure(
                        reason=RUNTIME_TURN_END,
                        message="Required Turn completion was interrupted.",
                        module="loop",
                        kind=LoopFailureKind.CONTRACT_VIOLATION.value,
                    )

                finalizer = asyncio.create_task(
                    self._completion_pipeline.run(
                        TurnCompletion(
                            context_completion=context_completion,
                            active_day=active_day,
                            status=execution_status,
                            output=output,
                            exhausted=exhausted,
                            completion=completion,
                            failure=failure,
                            finish_failures=finish_failures,
                        ),
                        capture_failure=capture_finish_failure,
                    )
                )
                while not finalizer.done():
                    try:
                        await asyncio.shield(finalizer)
                    except asyncio.CancelledError as exc:
                        task_cancellation = task_cancellation or exc
                finalized = finalizer.result()
                finish_failures = finalized.finish_failures
                completion_committed = not finish_failures
                failure = failure or (finish_failures[0] if finish_failures else None)
        finally:
            closer = asyncio.create_task(self._context.close_segments())
            while not closer.done():
                try:
                    await asyncio.shield(closer)
                except asyncio.CancelledError as exc:
                    task_cancellation = task_cancellation or exc
            cleanup_diagnostics.extend(closer.result())
        status, failure = self._outcome_status(
            output=output,
            completion=completion,
            completion_committed=completion_committed,
            exhausted=exhausted,
            stopped=stopped,
            transfer=transfer,
            failure=failure,
        )
        if task_cancellation is not None and status is TurnOutcomeStatus.STOPPED:
            status = TurnOutcomeStatus.CANCELLED
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
        elif status is not TurnOutcomeStatus.COMPLETED:
            self._emit_terminal_without_output(
                turn_scope,
                status=status,
                failure=failure,
            )
        self._emit(
            turn_scope,
            "turn.completed",
            ObservationLevel.VERBOSE,
            "Turn completed.",
            {
                "turn_id": turn_id,
                "has_output": status is TurnOutcomeStatus.ANSWERED,
                "status": status.value,
                "completion_committed": completion_committed,
                "exhausted": exhausted,
                "transfer_action": (
                    transfer.action.value if transfer is not None else None
                ),
            },
        )
        outcome = TurnOutcome(
            context_completion=context_completion,
            active_day=active_day,
            status=status,
            output=output,
            exhausted=exhausted,
            transfer=transfer,
            failure=failure,
            completion=completion,
            finish_failures=finish_failures,
            cleanup_diagnostics=tuple(cleanup_diagnostics),
        )
        if task_cancellation is not None:
            raise TurnExecutionCancelled(outcome) from task_cancellation
        return outcome

    async def _run_preparation(
        self,
        *,
        turn_id: str,
        turn_input: str,
        active_day: CalendarDay,
        scope: RunScope,
    ) -> _TurnBoundary | None:
        turn_frame = scope.nearest(RunLevel.TURN)
        if turn_frame is None:
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Turn preparation scope has no Turn frame")
            )
        while True:
            try:
                try:
                    await self._context.open_segments(active_day.value)
                except ContextError as exc:
                    raise self._context_bridge.from_context_error(exc) from exc
                signals = await self._preparation_pipeline.prepare(
                    TurnPreparationRequest(
                        turn_id=turn_id,
                        turn_input=turn_input,
                        active_day=active_day,
                        scope=scope,
                    )
                )
                (await self._commit_preparation_signals(signals, scope=scope))
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
                LoopInvariantError(f"Unsupported Turn preparation transfer: {transfer}")
            )

    async def _commit_preparation_signals(
        self,
        signals: tuple[Signal, ...],
        *,
        scope: RunScope,
    ) -> None:
        if not signals:
            return
        preparation_results = await self._signal_consumer.emit_and_consume(
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
                            }
                            for result in rejected[:8]
                        ],
                        "rejected_count": len(rejected),
                    }
                ),
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

    async def _record_cycle_limit(self, scope: RunScope) -> None:
        (
            await self._signal_consumer.emit_and_consume(
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
            failure_from_runtime(cause) if isinstance(cause, RuntimeException) else None
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
        if failure is not None:
            return TurnOutcomeStatus.FAILED, failure
        if output is not None and completion_committed:
            return TurnOutcomeStatus.ANSWERED, None
        if completion is not None and completion_committed:
            if completion.get("kind") == "awaiting_user":
                return TurnOutcomeStatus.AWAITING_USER, None
            return TurnOutcomeStatus.COMPLETED, None
        if exhausted:
            return TurnOutcomeStatus.EXHAUSTED, None
        if stopped or transfer is not None:
            return TurnOutcomeStatus.STOPPED, None
        return (
            TurnOutcomeStatus.FAILED,
            TurnFailure(
                reason=RUNTIME_TURN_END,
                message="Turn ended without a valid completion.",
                module="loop",
                kind=LoopFailureKind.INTERNAL_FAILURE.value,
            ),
        )

    def _emit_terminal_without_output(
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
                    **(
                        {"feedback": list(failure.feedback)} if failure.feedback else {}
                    ),
                }
            )
        messages = {
            TurnOutcomeStatus.CANCELLED: "Turn was cancelled.",
            TurnOutcomeStatus.AWAITING_USER: "Turn ended while waiting for a user reply.",
            TurnOutcomeStatus.EXHAUSTED: "Turn exhausted its cycle limit.",
            TurnOutcomeStatus.STOPPED: "Turn stopped before completion.",
            TurnOutcomeStatus.FAILED: (
                failure.message if failure is not None else "Turn failed."
            ),
        }
        message = messages.get(status)
        if message is None:
            raise LoopInvariantError(
                f"Turn status does not require a terminal event: {status.value}"
            )
        self._emit(
            scope,
            f"turn.{status.value}",
            ObservationLevel.NORMAL,
            message,
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

    def _set_active_scope(
        self,
        scope: RunScope | None,
        cancellation: TurnCancellation | None = None,
    ) -> None:
        with self._active_scope_lock:
            self._active_scope = scope
            self._active_cancellation = cancellation if scope is not None else None

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


def _no_turn_output(_completion: JsonObject | None) -> TurnOutput | None:
    return None
