"""Loop phase execution units."""

from __future__ import annotations


from tinysoul.kernel.action.call import ActionCall
from tinysoul.kernel.action import (
    ActionEngine,
    ActionError,
    ActionNormalization,
    ActionPhaseResult,
)
from tinysoul.kernel.context import (
    ContextEngine,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
)
from tinysoul.kernel.context.errors import ContextError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.messages import AssistantMessage, TextPart
from tinysoul.llm.protocol.requests import ModelContextOverflowPolicy, TaskCall
from tinysoul.llm.protocol.responses import TaskResult, TaskResultStatus
from tinysoul.runtime import (
    CyclePhase,
    RunScope,
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

from ..interaction.cancellation import TurnCancellation
from ..context_signals import ContextSignalConsumer
from ..prompts import DomainSkillProvider, EmptyDomainSkillProvider, phase2_task_prompt
from ..signals import LoopTraceNoteKind

from .contracts import LLMRunner, PhaseFailure, Phase2Outcome
from .tasks import (
    _required_tool_settings,
    _turn_task_cancellation,
    _task_result_feedback,
)


class Phase2Unit:
    """Generate concrete action calls for selected domains."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        action: ActionEngine,
        llm: LLMRunner,
        bus: SignalBus,
        task_profile: str,
        domain_skills: DomainSkillProvider | None = None,
        context_bridge: RuntimeContextBridge | None = None,
        action_bridge: RuntimeActionBridge | None = None,
        signal_consumer: ContextSignalConsumer | None = None,
        observations: ObservationEmitter | None = None,
        turn_guidance: tuple[str, ...] = (),
    ) -> None:
        self._context = context
        self._action = action
        self._llm = llm
        self._bus = bus
        self._task_profile = task_profile
        self._domain_skills = domain_skills or EmptyDomainSkillProvider()
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._action_bridge = action_bridge or RuntimeActionBridge()
        self._signal_consumer = signal_consumer or ContextSignalConsumer(context, bus)
        self._observations = observations or NullObservationEmitter()
        self._turn_guidance = tuple(turn_guidance)

    async def run(
        self,
        *,
        selected_domains: tuple[str, ...],
        scope: RunScope,
        cycle_id: str,
        turn_id: str = "",
        cancellation: TurnCancellation | None = None,
    ) -> Phase2Outcome:
        try:
            preparation = self._action.phase2_scope(
                selected_domains,
                turn_id=turn_id,
                cycle_id=cycle_id,
            )
        except ActionError as exc:
            raise self._action_bridge.from_action_error(exc) from exc
        if preparation.tool_scope is None:
            (
                await self._emit_phase_results(
                    preparation.phase_results, scope=scope, cycle_id=cycle_id
                )
            )
            return Phase2Outcome(
                normalization=ActionNormalization(),
                phase_results=preparation.phase_results,
            )

        try:
            messages = self._context.compose(
                phase2_task_prompt(
                    selected_domains=selected_domains,
                    domain_skills=await self._domain_skills.guidance_for(
                        selected_domains
                    ),
                    feedback=(),
                    turn_guidance=self._turn_guidance,
                )
            )
        except ContextError as exc:
            raise self._context_bridge.from_context_error(exc) from exc
        result = await self._llm.run(
            TaskCall(
                profile=self._task_profile,
                messages=messages,
                tool_scope=preparation.tool_scope,
                settings=_required_tool_settings(),
                scope=scope,
                context_overflow_policy=ModelContextOverflowPolicy.REQUEST_RECOVERY,
                cancellation=_turn_task_cancellation(cancellation),
            )
        )
        self._context.mark_model_consumed(messages)
        if result.status is TaskResultStatus.FAILURE:
            feedback = (_task_result_feedback(result),)
            (
                await self._emit_note(
                    {
                        "kind": LoopTraceNoteKind.PHASE2_TASK_FAILED.value,
                        "reason": "framework_task_failure",
                        "feedback": list(feedback),
                    },
                    scope=scope,
                    cycle_id=cycle_id,
                )
            )
            return Phase2Outcome(
                normalization=ActionNormalization(),
                failure=PhaseFailure(
                    phase=CyclePhase.PHASE2,
                    reason="framework_task_failure",
                    feedback=feedback,
                ),
            )
        self._context.register_action_calls(
            tuple(
                ActionCall(
                    call_id=call.id,
                    action_name=call.name,
                    params=call.arguments,
                    sequence=index,
                )
                for index, call in enumerate(result.tool_calls, start=1)
            ),
            cycle_id=cycle_id,
        )
        (await self._emit_decision(result, scope=scope, cycle_id=cycle_id))
        try:
            normalization = self._action.normalize(result.tool_calls)
        except ActionError as exc:
            raise self._action_bridge.from_action_error(exc) from exc
        for local_result in normalization.results:
            self._context.record_action_result(local_result, cycle_id=cycle_id)
        self._observe_action_calls(normalization, scope=scope)
        return Phase2Outcome(normalization=normalization)

    def _observe_action_calls(
        self,
        normalization: ActionNormalization,
        *,
        scope: RunScope,
    ) -> None:
        if not observation_enabled(self._observations, ObservationLevel.VERBOSE):
            return
        for call in normalization.calls:
            emit_observation(
                self._observations,
                ObservationEvent(
                    name="action.call",
                    level=ObservationLevel.VERBOSE,
                    source="loop.phase2",
                    scope=scope,
                    message=f"Action call prepared: {call.action_name}.",
                    payload=self._action.render_call_trace_payload(call),
                ),
            )

    async def _emit_decision(
        self,
        result: TaskResult,
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        parts = ()
        if result.raw_response.answer_text:
            parts = (TextPart(result.raw_response.answer_text),)
        message = AssistantMessage.from_parts(
            *parts,
            reasoning=result.raw_response.reasoning,
            tool_calls=result.tool_calls,
            label="decision",
        )
        (
            await self._signal_consumer.emit_and_consume(
                (
                    build_trace_decision_signal(
                        message,
                        scope=scope,
                        source="loop.phase2",
                        cycle_id=cycle_id,
                        phase=CyclePhase.PHASE2,
                    ),
                ),
                scope=scope,
            )
        )

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
                source="loop.phase2",
                cycle_id=cycle_id,
                phase=CyclePhase.PHASE2,
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
                        source="loop.phase2",
                        cycle_id=cycle_id,
                        phase=CyclePhase.PHASE2,
                    ),
                ),
                scope=scope,
            )
        )
