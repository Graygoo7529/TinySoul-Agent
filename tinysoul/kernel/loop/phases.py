"""Loop phase execution units."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.kernel.action.core.call import ActionCall
from tinysoul.kernel.action import (
    ActionEngine,
    ActionError,
    ActionExecutionContext,
    ActionNormalization,
    ActionPhaseResult,
    ActionResult,
    ActionResultStatus,
)
from tinysoul.kernel.context import (
    ContextEngine,
    ControlResult,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
)
from tinysoul.kernel.context.errors import ContextError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import AssistantMessage, TextPart
from tinysoul.llm.requests import (
    CallSettings,
    ModelContextOverflowPolicy,
    TaskCall,
    TaskCancellation,
)
from tinysoul.llm.responses import AnswerFormat, TaskResult, TaskResultStatus
from tinysoul.llm.tools import ToolScope, ToolSelection, ToolSpec, ToolUse
from tinysoul.runtime import (
    CyclePhase,
    RunScope,
    RuntimeException,
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

from .cancellation import TurnCancellation
from .context_signals import ContextSignalConsumer
from .errors import LoopContractError, LoopError, LoopInvariantError
from .prompts import DomainSkillProvider, EmptyDomainSkillProvider, phase1_task_prompt, phase2_task_prompt
from .completion import question_from_results
from .inbox import QuestionRequest
from .signals import LoopTraceNoteKind

class LLMRunner(Protocol):
    """The LLM runner surface needed by loop phases."""

    async def run(self, call: TaskCall) -> TaskResult:
        """Run one LLM task call."""
        ...


@dataclass(frozen=True)
class PhaseFailure:
    """A model-correctable failure at a framework phase boundary."""

    phase: CyclePhase
    reason: str
    feedback: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.phase, CyclePhase):
            raise LoopContractError("PhaseFailure.phase must be a CyclePhase")
        if not self.reason:
            raise LoopContractError("PhaseFailure.reason must be non-empty")
        if any(not isinstance(item, str) or not item for item in self.feedback):
            raise LoopContractError(
                "PhaseFailure.feedback must contain non-empty strings"
            )
        object.__setattr__(self, "feedback", tuple(self.feedback))


@dataclass(frozen=True)
class Phase1Outcome:
    """Phase1 selected domains and local control feedback."""

    selected_domains: tuple[str, ...]
    control_results: tuple[ControlResult, ...] = field(default_factory=tuple)
    attempts: int = 1
    failure: PhaseFailure | None = None


@dataclass(frozen=True)
class Phase2Outcome:
    """Phase2 normalized action calls and local phase feedback."""

    normalization: ActionNormalization
    phase_results: tuple[ActionPhaseResult, ...] = field(default_factory=tuple)
    attempts: int = 1
    failure: PhaseFailure | None = None


@dataclass(frozen=True)
class Phase3Outcome:
    """Phase3 action results when the phase does not complete the Turn."""

    results: tuple[ActionResult, ...] = field(default_factory=tuple)
    phase_results: tuple[ActionPhaseResult, ...] = field(default_factory=tuple)
    completion: JsonObject | None = None
    question: QuestionRequest | None = None
    failure: PhaseFailure | None = None


class TurnCompletionDetector(Protocol):
    """Detect a successful Turn completion from Phase3 action results."""

    def detect(self, results: tuple[ActionResult, ...]) -> JsonObject | None: ...


class NoTurnCompletionDetector:
    def detect(self, results: tuple[ActionResult, ...]) -> JsonObject | None:
        return None


class Phase1Unit:
    """Update context controls and select action domains."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        action: ActionEngine,
        llm: LLMRunner,
        bus: SignalBus,
        task_profile: str,
        context_bridge: RuntimeContextBridge | None = None,
        action_bridge: RuntimeActionBridge | None = None,
        loop_bridge: RuntimeLoopBridge | None = None,
        signal_consumer: ContextSignalConsumer | None = None,
        turn_guidance: tuple[str, ...] = (),
    ) -> None:
        self._context = context
        self._action = action
        self._llm = llm
        self._bus = bus
        self._task_profile = task_profile
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._action_bridge = action_bridge or RuntimeActionBridge()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()
        self._signal_consumer = signal_consumer or ContextSignalConsumer(context, bus)
        self._turn_guidance = tuple(turn_guidance)

    async def run(
        self,
        *,
        scope: RunScope,
        cycle_id: str,
        cancellation: TurnCancellation | None = None,
        initial_feedback: tuple[str, ...] = (),
    ) -> Phase1Outcome:
        domain_prompt = self._action.phase1_domain_prompt()
        try:
            tool_scope = _merge_tool_scopes(
                self._context.control_scope(),
                self._action.phase1_scope(),
                forced_name=self._action.phase1_domain_tool_name(),
            )
            messages = self._context.compose(
                phase1_task_prompt(
                    domain_prompt=domain_prompt,
                    feedback=initial_feedback,
                    turn_guidance=self._turn_guidance,
                )
            )
        except ContextError as exc:
            raise self._context_bridge.from_context_error(exc) from exc
        except ActionError as exc:
            raise self._action_bridge.from_action_error(exc) from exc
        except LoopError as exc:
            raise self._loop_bridge.from_loop_error(exc) from exc

        result = await self._llm.run(
            TaskCall(
                profile=self._task_profile,
                messages=messages,
                tool_scope=tool_scope,
                settings=_required_tool_settings(),
                scope=scope,
                context_overflow_policy=ModelContextOverflowPolicy.REQUEST_RECOVERY,
                cancellation=_turn_task_cancellation(cancellation),
            )
        )
        if result.status is TaskResultStatus.FAILURE:
            return (await self._failed(
                scope=scope,
                cycle_id=cycle_id,
                reason="framework_task_failure",
                feedback=(_task_result_feedback(result),),
            ))

        selection = self._action.normalize_domain_selection(result.tool_calls)
        control_calls = tuple(
            call
            for call in result.tool_calls
            if call.name != self._action.phase1_domain_tool_name()
        )
        try:
            normalization = self._context.normalize_controls(
                control_calls,
                scope=scope,
            )
            consume_results = (await self._signal_consumer.emit_and_consume(
                normalization.signals,
                scope=scope,
            ))
        except ContextError as exc:
            raise self._context_bridge.from_context_error(exc) from exc
        control_results = (*normalization.results, *consume_results)
        if control_results:
            (await self._emit_phase_note(
                {
                    "kind": LoopTraceNoteKind.PHASE1_CONTROL_FEEDBACK.value,
                    "results": [
                        _control_result_payload(result)
                        for result in control_results
                    ],
                },
                scope=scope,
                cycle_id=cycle_id,
            ))
        feedback = selection.feedback or (
            ("Phase1 did not select any action domain.",)
            if not selection.selected_domains
            else ()
        )
        if feedback:
            return (await self._failed(
                scope=scope,
                cycle_id=cycle_id,
                reason="invalid_domain_selection",
                feedback=tuple(feedback),
                control_results=control_results,
            ))
        return Phase1Outcome(
            selected_domains=selection.selected_domains,
            control_results=control_results,
        )

    async def _failed(
        self,
        *,
        scope: RunScope,
        cycle_id: str,
        reason: str,
        feedback: tuple[str, ...],
        control_results: tuple[ControlResult, ...] = (),
    ) -> Phase1Outcome:
        (await self._emit_phase_note(
            {
                "kind": LoopTraceNoteKind.PHASE1_TASK_FAILED.value,
                "reason": reason,
                "feedback": list(feedback),
            },
            scope=scope,
            cycle_id=cycle_id,
        ))
        return Phase1Outcome(
            selected_domains=(),
            control_results=control_results,
            failure=PhaseFailure(
                phase=CyclePhase.PHASE1,
                reason=reason,
                feedback=feedback,
            ),
        )

    async def _emit_phase_note(
        self,
        note: JsonObject,
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        (await self._signal_consumer.emit_and_consume(
            (
                build_trace_phase_note_signal(
                    note,
                    scope=scope,
                    source="loop.phase1",
                    cycle_id=cycle_id,
                    phase=CyclePhase.PHASE1,
                ),
            ),
            scope=scope,
        ))


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
            (await self._emit_phase_results(preparation.phase_results, scope=scope, cycle_id=cycle_id))
            return Phase2Outcome(
                normalization=ActionNormalization(),
                phase_results=preparation.phase_results,
            )

        try:
            messages = self._context.compose(
                phase2_task_prompt(
                    selected_domains=selected_domains,
                    domain_skills=self._domain_skills.guidance_for(selected_domains),
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
        if result.status is TaskResultStatus.FAILURE:
            feedback = (_task_result_feedback(result),)
            (await self._emit_note(
                {
                    "kind": LoopTraceNoteKind.PHASE2_TASK_FAILED.value,
                    "reason": "framework_task_failure",
                    "feedback": list(feedback),
                },
                scope=scope,
                cycle_id=cycle_id,
            ))
            return Phase2Outcome(
                normalization=ActionNormalization(),
                failure=PhaseFailure(
                    phase=CyclePhase.PHASE2,
                    reason="framework_task_failure",
                    feedback=feedback,
                ),
            )
        self._context.register_action_calls(tuple(
            ActionCall(call_id=call.id, action_name=call.name,
                       params=call.arguments, sequence=index)
            for index, call in enumerate(result.tool_calls, start=1)
        ), cycle_id=cycle_id)
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
        (await self._signal_consumer.emit_and_consume(
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
        ))

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
        (await self._signal_consumer.emit_and_consume(
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
        ))


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
            execution_results = (await self._action.run_batch(
                preparation.batch,
                context=ActionExecutionContext(
                    record_execution=self._context.record_execution,
                    signal_bus=self._bus,
                    module_runner=self._module_runner,
                    cancelled=(
                        cancellation.requested
                        if cancellation is not None
                        else None
                    ),
                ),
            ))
        except ActionError as exc:
            raise self._action_bridge.from_action_error(exc) from exc

        results = normalization.merged_results(
            (*preparation.results, *execution_results)
        )
        await self._consume_action_effects(scope=scope)
        self._observe_action_results(results, scope=scope)
        (await self._emit_action_results(results, scope=scope, cycle_id=cycle_id))
        phase_results = preparation.phase_results
        (await self._emit_phase_results(
            phase_results,
            scope=scope,
            cycle_id=cycle_id,
        ))
        try:
            intents = [item for item in results
                       if item.action_name in {"core.answer", "core.ask"}
                       and item.status is ActionResultStatus.SUCCESS]
            if len(intents) > 1:
                return Phase3Outcome(results=results, phase_results=phase_results,
                                     failure=PhaseFailure(
                                         phase=CyclePhase.PHASE3, reason="conflicting_turn_intents",
                                         feedback=("Choose exactly one question or final answer in a Cycle.",),
                                     ))
            completion = self._completion_detector.detect(results)
            question = question_from_results(results)
        except LoopError as exc:
            raise self._loop_bridge.from_loop_error(exc) from exc
        return Phase3Outcome(
            results=results,
            phase_results=phase_results,
            completion=completion,
            question=question,
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
        consume_results = (await self._signal_consumer.consume(scope=scope))
        if consume_results:
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError(
                    "Context rejected an internal Action update"
                ),
                payload={
                    "results": [
                        _control_result_payload(result)
                        for result in consume_results
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
                    canonical_message=(
                        canonical if canonical is not visible else None
                    ),
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
        (await self._signal_consumer.emit_and_consume(
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
        ))


def _merge_tool_scopes(
    *scopes: ToolScope,
    forced_name: str | None = None,
) -> ToolScope:
    tools: list[ToolSpec] = []
    names: set[str] = set()
    for scope in scopes:
        for tool in scope.visible_tools():
            if tool.name in names:
                raise LoopContractError(f"Duplicate tool in merged scope: {tool.name}")
            tools.append(tool)
            names.add(tool.name)
    allowed_names = tuple(tool.name for tool in tools)
    return ToolScope(
        tools=tuple(tools),
        selection=ToolSelection(
            allowed_names=allowed_names,
            forced_name=forced_name,
        ),
    )


def _required_tool_settings() -> CallSettings:
    return CallSettings(answer_format=AnswerFormat.NONE, tool_use=ToolUse.REQUIRED)


def _turn_task_cancellation(
    cancellation: TurnCancellation | None,
) -> TaskCancellation | None:
    if cancellation is None:
        return None
    return TaskCancellation(
        cancelled=cancellation.requested,
        remaining_seconds=lambda: None,
        reason=lambda: "turn_cancelled",
    )


def _task_result_feedback(result: TaskResult) -> str:
    if result.failure is None or not result.failure.model_feedback:
        return "LLM task output did not satisfy the phase protocol."
    return result.failure.model_feedback


def _control_result_payload(result: ControlResult) -> JsonObject:
    return {
        "call_id": result.call_id,
        "tool_name": result.tool_name,
        "status": result.status.value,
        "stage": result.stage.value,
        "feedback": result.model_feedback,
        "frame_data": result.frame_data,
    }
