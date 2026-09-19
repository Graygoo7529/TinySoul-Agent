"""Loop phase execution units."""

from __future__ import annotations


from tinysoul.kernel.action import (
    ActionEngine,
    ActionError,
    ActionExecutionContext,
    ActionNormalization,
    ActionPhaseResult,
    ActionResult,
)
from tinysoul.kernel.context import (
    ContextEngine,
    build_trace_action_result_signal,
    build_trace_phase_note_signal,
)
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import (
    CyclePhase,
    RunScope,
    RuntimeModuleRunner,
    Signal,
    SignalBus,
    NullObservationEmitter,
    ObservationEmitter,
    ObservationEvent,
    ObservationLevel,
    emit_observation,
    observation_enabled,
)
from tinysoul.kernel.action.runtime_bridge import RuntimeActionBridge
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.kernel.loop.runtime_bridge import RuntimeLoopBridge

from ..interaction.cancellation import TurnCancellation
from ..context_signals import ContextSignalConsumer
from ..errors import LoopError, LoopInvariantError
from ..lifecycle.completion import question_from_results, wait_from_results
from ..signals import LoopTraceNoteKind

from .contracts import (
    PhaseFailure,
    Phase3Outcome,
    TurnCompletionDetector,
    NoTurnCompletionDetector,
)
from .tasks import _control_result_payload


class Phase3Unit:
    """Execute normalized action calls and write action feedback into context."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        action: ActionEngine,
        bus: SignalBus,
        module_runner: RuntimeModuleRunner | None = None,
        context_bridge: RuntimeContextBridge | None = None,
        action_bridge: RuntimeActionBridge | None = None,
        loop_bridge: RuntimeLoopBridge | None = None,
        signal_consumer: ContextSignalConsumer | None = None,
        observations: ObservationEmitter | None = None,
        completion_detector: TurnCompletionDetector | None = None,
    ) -> None:
        self._context = context
        self._action = action
        self._bus = bus
        self._module_runner = module_runner
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._action_bridge = action_bridge or RuntimeActionBridge()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()
        self._signal_consumer = signal_consumer or ContextSignalConsumer(context, bus)
        self._observations = observations or NullObservationEmitter()
        self._completion_detector = completion_detector or NoTurnCompletionDetector()

    async def run(
        self,
        *,
        normalization: ActionNormalization,
        scope: RunScope,
        cycle_id: str,
        turn_id: str = "",
        cancellation: TurnCancellation | None = None,
    ) -> Phase3Outcome:
        intents = [
            call
            for call in normalization.calls
            if call.action_name
            in {
                "core.answer",
                "core.ask",
                "core.wait",
                "core.job.wait",
            }
        ]
        if len(intents) > 1:
            return Phase3Outcome(
                failure=PhaseFailure(
                    phase=CyclePhase.PHASE3,
                    reason="conflicting_turn_intents",
                    feedback=(
                        "Choose one answer, question or wait intent per Cycle; no actions were executed.",
                    ),
                )
            )
        try:
            self._context.register_action_calls(normalization.calls, cycle_id=cycle_id)
            preparation = self._action.prepare_batch(
                normalization.calls,
                scope=scope,
                turn_id=turn_id,
                cycle_id=cycle_id,
            )
            for local_result in preparation.results:
                self._context.record_action_result(local_result, cycle_id=cycle_id)
            execution_results = await self._action.run_batch(
                preparation.batch,
                context=ActionExecutionContext(
                    record_execution=self._context.record_execution,
                    signal_bus=self._bus,
                    module_runner=self._module_runner,
                    cancelled=(
                        cancellation.requested if cancellation is not None else None
                    ),
                ),
            )
        except ActionError as exc:
            raise self._action_bridge.from_action_error(exc) from exc

        results = normalization.merged_results(
            (*preparation.results, *execution_results)
        )
        await self._consume_action_effects(scope=scope)
        self._observe_action_results(results, scope=scope)
        (await self._emit_action_results(results, scope=scope, cycle_id=cycle_id))
        phase_results = preparation.phase_results
        (
            await self._emit_phase_results(
                phase_results,
                scope=scope,
                cycle_id=cycle_id,
            )
        )
        try:
            completion = self._completion_detector.detect(results)
            question = question_from_results(results)
            wait = wait_from_results(results)
        except LoopError as exc:
            raise self._loop_bridge.from_loop_error(exc) from exc
        return Phase3Outcome(
            results=results,
            phase_results=phase_results,
            completion=completion,
            question=question,
            wait=wait,
        )

    def _observe_action_results(
        self,
        results: tuple[ActionResult, ...],
        *,
        scope: RunScope,
    ) -> None:
        if not observation_enabled(self._observations, ObservationLevel.VERBOSE):
            return
        for result in results:
            emit_observation(
                self._observations,
                ObservationEvent(
                    name="action.result",
                    level=ObservationLevel.VERBOSE,
                    source="loop.phase3",
                    scope=scope,
                    message=(
                        f"Action result: {result.action_name} "
                        f"{result.status.value}."
                    ),
                    payload=self._action.render_result_trace_payload(result),
                ),
            )

    async def _consume_action_effects(
        self,
        *,
        scope: RunScope,
    ) -> None:
        consume_results = await self._signal_consumer.consume(scope=scope)
        if consume_results:
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError("Context rejected an internal Action update"),
                payload={
                    "results": [
                        _control_result_payload(result) for result in consume_results
                    ]
                },
            )

    async def _emit_action_results(
        self,
        results: tuple[ActionResult, ...],
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        rendered_results = self._action.render_tool_results(results)
        signals: list[Signal] = []
        for rendered in rendered_results:
            visible = rendered.visible_message
            canonical = rendered.canonical_message
            signals.append(
                build_trace_action_result_signal(
                    visible,
                    scope=scope,
                    source="loop.phase3",
                    cycle_id=cycle_id,
                    origin_refs=rendered.origin_refs,
                    canonical_message=(canonical if canonical is not visible else None),
                )
            )
        (await self._signal_consumer.emit_and_consume(tuple(signals), scope=scope))

    async def _emit_phase_results(
        self,
        results: tuple[ActionPhaseResult, ...],
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        signals = tuple(
            build_trace_phase_note_signal(
                {
                    "kind": LoopTraceNoteKind.ACTION_PHASE_RESULT.value,
                    "result": self._action.render_phase_trace_payload(result),
                },
                scope=scope,
                source="loop.phase3",
                cycle_id=cycle_id,
                phase=CyclePhase.PHASE3,
            )
            for result in results
        )
        if signals:
            (await self._signal_consumer.emit_and_consume(signals, scope=scope))

    async def _emit_note(
        self,
        note: JsonObject,
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        (
            await self._signal_consumer.emit_and_consume(
                (
                    build_trace_phase_note_signal(
                        note,
                        scope=scope,
                        source="loop.phase3",
                        cycle_id=cycle_id,
                        phase=CyclePhase.PHASE3,
                    ),
                ),
                scope=scope,
            )
        )
