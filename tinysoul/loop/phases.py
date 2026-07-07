"""Loop phase execution units."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.action import (
    ActionEngine,
    ActionNormalization,
    ActionPhaseResult,
    ActionResult,
    ActionResultStatus,
)
from tinysoul.action.core.errors import ActionError
from tinysoul.action.core.executor import ActionExecutionContext
from tinysoul.context import (
    ContextEngine,
    ControlResult,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
)
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import AssistantMessage, TextPart
from tinysoul.llm.requests import CallSettings, TaskCall, TaskProfile
from tinysoul.llm.responses import AnswerFormat, TaskResult, TaskResultStatus
from tinysoul.llm.tools import ToolCallRecord, ToolScope, ToolSelection, ToolSpec, ToolUse
from tinysoul.runtime import CyclePhase, RunScope, SignalBus
from tinysoul.runtime.bridge import RuntimeActionBridge, RuntimeContextBridge, RuntimeLoopBridge

from .errors import LoopContractError
from .prompts import DomainGuidanceProvider, EmptyDomainGuidanceProvider, phase1_task_prompt, phase2_task_prompt

PHASE1_DOMAIN_TOOL = "select_action_domains"
ANSWER_ACTION = "core.answer"


class LLMRunner(Protocol):
    """The LLM runner surface needed by loop phases."""

    def run(self, call: TaskCall) -> TaskResult:
        """Run one LLM task call."""
        ...


@dataclass(frozen=True)
class Phase1Outcome:
    """Phase1 selected domains and local control feedback."""

    selected_domains: tuple[str, ...]
    control_results: tuple[ControlResult, ...] = field(default_factory=tuple)
    attempts: int = 1


@dataclass(frozen=True)
class Phase2Outcome:
    """Phase2 normalized action calls and local phase feedback."""

    normalization: ActionNormalization
    phase_results: tuple[ActionPhaseResult, ...] = field(default_factory=tuple)
    attempts: int = 1


@dataclass(frozen=True)
class Phase3Outcome:
    """Phase3 action results and turn completion marker."""

    results: tuple[ActionResult, ...] = field(default_factory=tuple)
    phase_results: tuple[ActionPhaseResult, ...] = field(default_factory=tuple)
    answered: bool = False


class Phase1Unit:
    """Update context controls and select action domains."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        action: ActionEngine,
        llm: LLMRunner,
        bus: SignalBus,
        retry_limit: int,
        context_bridge: RuntimeContextBridge | None = None,
        action_bridge: RuntimeActionBridge | None = None,
        loop_bridge: RuntimeLoopBridge | None = None,
    ) -> None:
        self._context = context
        self._action = action
        self._llm = llm
        self._bus = bus
        self._retry_limit = retry_limit
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._action_bridge = action_bridge or RuntimeActionBridge()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()

    def run(self, *, scope: RunScope, cycle_id: str) -> Phase1Outcome:
        feedback: list[str] = []
        domain_prompt = self._action.phase1_domain_prompt()
        last_control_results: tuple[ControlResult, ...] = ()
        for attempt in range(1, self._retry_limit + 1):
            try:
                tool_scope = _merge_tool_scopes(
                    self._context.control_scope(),
                    self._action.phase1_scope(),
                    forced_name=PHASE1_DOMAIN_TOOL,
                )
                messages = self._context.compose(
                    phase1_task_prompt(
                        domain_prompt=domain_prompt,
                        feedback=tuple(feedback),
                    )
                )
            except ContextError as exc:
                raise self._context_bridge.from_context_error(exc) from exc
            except ActionError as exc:
                raise self._action_bridge.from_action_error(exc) from exc

            result = self._llm.run(
                TaskCall(
                    profile=TaskProfile.FRAMEWORK,
                    messages=messages,
                    tool_scope=tool_scope,
                    settings=_required_tool_settings(),
                )
            )
            if result.status is TaskResultStatus.FAILURE:
                feedback.append(_task_result_feedback(result))
                continue

            selected, selection_feedback = self._selected_domains(result.tool_calls)
            if selection_feedback:
                feedback.extend(selection_feedback)
                continue
            control_calls = tuple(
                call for call in result.tool_calls if call.name != PHASE1_DOMAIN_TOOL
            )
            try:
                normalization = self._context.normalize_controls(control_calls, scope=scope)
                for signal in normalization.signals:
                    self._bus.emit(signal)
                consume_results = self._context.consume_signals(self._bus)
            except ContextError as exc:
                raise self._context_bridge.from_context_error(exc) from exc
            last_control_results = (*normalization.results, *consume_results)
            if last_control_results:
                self._emit_phase_note(
                    {
                        "kind": "phase1_control_feedback",
                        "results": [
                            _control_result_payload(result)
                            for result in last_control_results
                        ],
                    },
                    scope=scope,
                    cycle_id=cycle_id,
                )
            return Phase1Outcome(
                selected_domains=selected,
                control_results=last_control_results,
                attempts=attempt,
            )
        raise self._loop_bridge.from_loop_error(
            LoopContractError("Phase1 did not produce a valid domain selection"),
            payload={"feedback": list(feedback)},
        )

    def _selected_domains(
        self,
        tool_calls: tuple[ToolCallRecord, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        selections = tuple(call for call in tool_calls if call.name == PHASE1_DOMAIN_TOOL)
        if not selections:
            return (), ("Phase1 must call select_action_domains.",)
        if len(selections) > 1:
            return (), ("Phase1 must call select_action_domains only once.",)
        value = selections[0].arguments.get("domains")
        if not isinstance(value, list) or not value:
            return (), ("select_action_domains.domains must be a non-empty string list.",)
        result: list[str] = []
        feedback: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str) or not item:
                feedback.append("select_action_domains.domains must contain non-empty strings.")
                continue
            if item in seen:
                continue
            seen.add(item)
            if not self._action.catalog.has_domain(item):
                feedback.append(f"Unknown action domain: {item}")
                continue
            if not self._action.catalog.actions_in_domain(item):
                feedback.append(f"Action domain has no available actions: {item}")
                continue
            result.append(item)
        if not result and not feedback:
            feedback.append("select_action_domains.domains contained no usable domains.")
        return tuple(result), tuple(feedback)

    def _emit_phase_note(
        self,
        note: JsonObject,
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        self._bus.emit(
            build_trace_phase_note_signal(
                note,
                scope=scope,
                source="loop.phase1",
                cycle_id=cycle_id,
                phase=CyclePhase.PHASE1,
            )
        )
        self._context.consume_signals(self._bus)


class Phase2Unit:
    """Generate concrete action calls for selected domains."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        action: ActionEngine,
        llm: LLMRunner,
        bus: SignalBus,
        retry_limit: int,
        guidance: DomainGuidanceProvider | None = None,
        context_bridge: RuntimeContextBridge | None = None,
        action_bridge: RuntimeActionBridge | None = None,
    ) -> None:
        self._context = context
        self._action = action
        self._llm = llm
        self._bus = bus
        self._retry_limit = retry_limit
        self._guidance = guidance or EmptyDomainGuidanceProvider()
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._action_bridge = action_bridge or RuntimeActionBridge()

    def run(
        self,
        *,
        selected_domains: tuple[str, ...],
        scope: RunScope,
        cycle_id: str,
        turn_id: str = "",
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
            self._emit_phase_results(preparation.phase_results, scope=scope, cycle_id=cycle_id)
            return Phase2Outcome(
                normalization=ActionNormalization(),
                phase_results=preparation.phase_results,
            )

        feedback: list[str] = []
        for attempt in range(1, self._retry_limit + 1):
            try:
                messages = self._context.compose(
                    phase2_task_prompt(
                        selected_domains=selected_domains,
                        domain_guidance=self._guidance.guidance_for(selected_domains),
                        feedback=tuple(feedback),
                    )
                )
            except ContextError as exc:
                raise self._context_bridge.from_context_error(exc) from exc
            result = self._llm.run(
                TaskCall(
                    profile=TaskProfile.FRAMEWORK,
                    messages=messages,
                    tool_scope=preparation.tool_scope,
                    settings=_required_tool_settings(),
                )
            )
            if result.status is TaskResultStatus.FAILURE:
                feedback.append(_task_result_feedback(result))
                continue
            self._emit_decision(result, scope=scope, cycle_id=cycle_id)
            try:
                normalization = self._action.normalize(result.tool_calls)
            except ActionError as exc:
                raise self._action_bridge.from_action_error(exc) from exc
            return Phase2Outcome(normalization=normalization, attempts=attempt)

        self._emit_note(
            {
                "kind": "phase2_task_failed",
                "feedback": list(feedback),
            },
            scope=scope,
            cycle_id=cycle_id,
        )
        return Phase2Outcome(normalization=ActionNormalization(), attempts=self._retry_limit)

    def _emit_decision(
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
        self._bus.emit(
            build_trace_decision_signal(
                message,
                scope=scope,
                source="loop.phase2",
                cycle_id=cycle_id,
                phase=CyclePhase.PHASE2,
            )
        )
        self._context.consume_signals(self._bus)

    def _emit_phase_results(
        self,
        results: tuple[ActionPhaseResult, ...],
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        for result in results:
            self._emit_note(
                {
                    "kind": "action_phase_result",
                    "result": self._action.renderer.render_phase_trace_payload(result),
                },
                scope=scope,
                cycle_id=cycle_id,
            )

    def _emit_note(
        self,
        note: JsonObject,
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        self._bus.emit(
            build_trace_phase_note_signal(
                note,
                scope=scope,
                source="loop.phase2",
                cycle_id=cycle_id,
                phase=CyclePhase.PHASE2,
            )
        )
        self._context.consume_signals(self._bus)


class Phase3Unit:
    """Execute normalized action calls and write action feedback into context."""

    def __init__(
        self,
        *,
        context: ContextEngine,
        action: ActionEngine,
        bus: SignalBus,
        context_bridge: RuntimeContextBridge | None = None,
        action_bridge: RuntimeActionBridge | None = None,
    ) -> None:
        self._context = context
        self._action = action
        self._bus = bus
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._action_bridge = action_bridge or RuntimeActionBridge()

    def run(
        self,
        *,
        normalization: ActionNormalization,
        scope: RunScope,
        cycle_id: str,
        turn_id: str = "",
    ) -> Phase3Outcome:
        try:
            preparation = self._action.prepare_batch(
                normalization.calls,
                scope=scope,
                turn_id=turn_id,
                cycle_id=cycle_id,
            )
            execution_results = self._action.run_batch(
                preparation.batch,
                context=ActionExecutionContext(signal_bus=self._bus),
            )
        except ActionError as exc:
            raise self._action_bridge.from_action_error(exc) from exc

        results = normalization.merged_results(
            (*preparation.results, *execution_results)
        )
        self._emit_action_results(results, scope=scope, cycle_id=cycle_id)
        self._emit_phase_results(
            preparation.phase_results,
            scope=scope,
            cycle_id=cycle_id,
        )
        answered = any(
            result.action_name == ANSWER_ACTION
            and result.status is ActionResultStatus.SUCCESS
            for result in results
        )
        return Phase3Outcome(
            results=results,
            phase_results=preparation.phase_results,
            answered=answered,
        )

    def _emit_action_results(
        self,
        results: tuple[ActionResult, ...],
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        for message in self._action.renderer.to_tool_result_messages(results):
            self._bus.emit(
                build_trace_action_result_signal(
                    message,
                    scope=scope,
                    source="loop.phase3",
                    cycle_id=cycle_id,
                )
            )
        self._consume_context_signals()

    def _emit_phase_results(
        self,
        results: tuple[ActionPhaseResult, ...],
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        for result in results:
            self._bus.emit(
                build_trace_phase_note_signal(
                    {
                        "kind": "action_phase_result",
                        "result": self._action.renderer.render_phase_trace_payload(result),
                    },
                    scope=scope,
                    source="loop.phase3",
                    cycle_id=cycle_id,
                    phase=CyclePhase.PHASE3,
                )
            )
        self._consume_context_signals()

    def _consume_context_signals(self) -> None:
        try:
            self._context.consume_signals(self._bus)
        except ContextError as exc:
            raise self._context_bridge.from_context_error(exc) from exc


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
