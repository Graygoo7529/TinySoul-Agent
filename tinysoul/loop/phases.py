"""Loop phase execution units."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.action import (
    ActionEngine,
    ActionError,
    ActionExecutionContext,
    ActionNormalization,
    ActionPhaseResult,
    ActionResult,
    ActionResultStatus,
)
from tinysoul.context import (
    ContextEngine,
    ControlResult,
    SIGNAL_WORKSPACE_SYNC,
    build_trace_action_result_signal,
    build_trace_decision_signal,
    build_trace_phase_note_signal,
)
from tinysoul.context.errors import ContextError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.messages import AssistantMessage, TextPart
from tinysoul.llm.requests import CallSettings, TaskCall, TaskProfile
from tinysoul.llm.responses import AnswerFormat, TaskResult, TaskResultStatus
from tinysoul.llm.tools import ToolScope, ToolSelection, ToolSpec, ToolUse
from tinysoul.runtime import (
    CyclePhase,
    RUNTIME_TURN_OUTPUT,
    RunScope,
    RuntimeException,
    RuntimeModuleRunner,
    SignalBus,
)
from tinysoul.runtime.bridge import RuntimeActionBridge, RuntimeContextBridge, RuntimeLoopBridge

from .context_signals import ContextSignalConsumer
from .errors import LoopContractError, LoopError, LoopInvariantError
from .prompts import DomainHowProvider, EmptyDomainHowProvider, phase1_task_prompt, phase2_task_prompt
from .signals import LoopTraceNoteKind

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
    """Phase3 action results when the phase does not complete the Turn."""

    results: tuple[ActionResult, ...] = field(default_factory=tuple)
    phase_results: tuple[ActionPhaseResult, ...] = field(default_factory=tuple)


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
        signal_consumer: ContextSignalConsumer | None = None,
    ) -> None:
        self._context = context
        self._action = action
        self._llm = llm
        self._bus = bus
        self._retry_limit = retry_limit
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._action_bridge = action_bridge or RuntimeActionBridge()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()
        self._signal_consumer = signal_consumer or ContextSignalConsumer(context, bus)

    def run(self, *, scope: RunScope, cycle_id: str) -> Phase1Outcome:
        feedback: list[str] = []
        domain_prompt = self._action.phase1_domain_prompt()
        last_control_results: tuple[ControlResult, ...] = ()
        for attempt in range(1, self._retry_limit + 1):
            try:
                tool_scope = _merge_tool_scopes(
                    self._context.control_scope(),
                    self._action.phase1_scope(),
                    forced_name=self._action.phase1_domain_tool_name(),
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
            except LoopError as exc:
                raise self._loop_bridge.from_loop_error(exc) from exc

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

            selection = self._action.normalize_domain_selection(result.tool_calls)
            if selection.feedback:
                feedback.extend(selection.feedback)
                continue
            control_calls = tuple(
                call
                for call in result.tool_calls
                if call.name != self._action.phase1_domain_tool_name()
            )
            try:
                normalization = self._context.normalize_controls(control_calls, scope=scope)
                consume_results = self._signal_consumer.emit_and_consume(
                    normalization.signals,
                    scope=scope,
                )
            except ContextError as exc:
                raise self._context_bridge.from_context_error(exc) from exc
            last_control_results = (*normalization.results, *consume_results)
            if last_control_results:
                self._emit_phase_note(
                    {
                        "kind": LoopTraceNoteKind.PHASE1_CONTROL_FEEDBACK.value,
                        "results": [
                            _control_result_payload(result)
                            for result in last_control_results
                        ],
                    },
                    scope=scope,
                    cycle_id=cycle_id,
                )
            return Phase1Outcome(
                selected_domains=selection.selected_domains,
                control_results=last_control_results,
                attempts=attempt,
            )
        raise self._loop_bridge.from_loop_error(
            LoopContractError("Phase1 did not produce a valid domain selection"),
            payload={"feedback": list(feedback)},
        )

    def _emit_phase_note(
        self,
        note: JsonObject,
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        self._signal_consumer.emit_and_consume(
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
        retry_limit: int,
        domain_how: DomainHowProvider | None = None,
        context_bridge: RuntimeContextBridge | None = None,
        action_bridge: RuntimeActionBridge | None = None,
        signal_consumer: ContextSignalConsumer | None = None,
    ) -> None:
        self._context = context
        self._action = action
        self._llm = llm
        self._bus = bus
        self._retry_limit = retry_limit
        self._domain_how = domain_how or EmptyDomainHowProvider()
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._action_bridge = action_bridge or RuntimeActionBridge()
        self._signal_consumer = signal_consumer or ContextSignalConsumer(context, bus)

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
                        domain_how=self._domain_how.guidance_for(selected_domains),
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
                "kind": LoopTraceNoteKind.PHASE2_TASK_FAILED.value,
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
        self._signal_consumer.emit_and_consume(
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

    def _emit_phase_results(
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
            self._signal_consumer.emit_and_consume(signals, scope=scope)

    def _emit_note(
        self,
        note: JsonObject,
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        self._signal_consumer.emit_and_consume(
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
    ) -> None:
        self._context = context
        self._action = action
        self._bus = bus
        self._module_runner = module_runner
        self._context_bridge = context_bridge or RuntimeContextBridge()
        self._action_bridge = action_bridge or RuntimeActionBridge()
        self._loop_bridge = loop_bridge or RuntimeLoopBridge()
        self._signal_consumer = signal_consumer or ContextSignalConsumer(context, bus)

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
                context=ActionExecutionContext(
                    signal_bus=self._bus,
                    module_runner=self._module_runner,
                ),
            )
        except ActionError as exc:
            raise self._action_bridge.from_action_error(exc) from exc

        results = normalization.merged_results(
            (*preparation.results, *execution_results)
        )
        expected_workspace_call_ids = frozenset(
            result.call_id
            for result in results
            if result.domain == "workspace"
            and result.status is ActionResultStatus.SUCCESS
        )
        self._consume_action_effects(
            scope=scope,
            expected_workspace_call_ids=expected_workspace_call_ids,
        )
        self._emit_action_results(results, scope=scope, cycle_id=cycle_id)
        phase_results = preparation.phase_results
        answer_results = tuple(
            result
            for result in results
            if result.action_name == ANSWER_ACTION
            and result.status is ActionResultStatus.SUCCESS
        )
        if len(answer_results) > 1:
            self._emit_note(
                {
                    "kind": LoopTraceNoteKind.MULTIPLE_TURN_OUTPUTS.value,
                    "status": "failed",
                    "phase": CyclePhase.PHASE3.value,
                    "feedback": (
                        "Phase3 produced multiple successful core.answer results; "
                        "produce exactly one final answer."
                    ),
                    "result_ids": [result.result_id for result in answer_results],
                },
                scope=scope,
                cycle_id=cycle_id,
            )
        self._emit_phase_results(
            phase_results,
            scope=scope,
            cycle_id=cycle_id,
        )
        if len(answer_results) == 1:
            self._raise_turn_output(answer_results[0])
        return Phase3Outcome(
            results=results,
            phase_results=phase_results,
        )

    def _consume_action_effects(
        self,
        *,
        scope: RunScope,
        expected_workspace_call_ids: frozenset[str],
    ) -> None:
        consume_results = self._signal_consumer.consume(scope=scope)
        workspace_failures = tuple(
            result
            for result in consume_results
            if result.tool_name == SIGNAL_WORKSPACE_SYNC
            and result.call_id in expected_workspace_call_ids
        )
        if workspace_failures:
            raise self._loop_bridge.from_loop_error(
                LoopInvariantError(
                    "Context rejected an authoritative Workspace snapshot"
                ),
                payload={
                    "results": [
                        _control_result_payload(result)
                        for result in workspace_failures
                    ]
                },
            )

    def _raise_turn_output(self, result: ActionResult) -> None:
        text = result.payload.get("text")
        references_value = result.payload.get("references", [])
        if not isinstance(text, str) or not text:
            raise self._loop_bridge.from_loop_error(
                LoopContractError(
                    "A successful core.answer result must contain non-empty text"
                )
            )
        if not isinstance(references_value, list) or any(
            not isinstance(item, str) or not item for item in references_value
        ):
            raise self._loop_bridge.from_loop_error(
                LoopContractError(
                    "A successful core.answer result must contain string references"
                )
            )
        raise RuntimeException(
            reason=RUNTIME_TURN_OUTPUT,
            message="The Turn produced its final output.",
            payload={
                "action": ANSWER_ACTION,
                "result_id": result.result_id,
                "text": text,
                "references": references_value,
            },
        )

    def _emit_action_results(
        self,
        results: tuple[ActionResult, ...],
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        signals = tuple(
            build_trace_action_result_signal(
                message,
                scope=scope,
                source="loop.phase3",
                cycle_id=cycle_id,
            )
            for message in self._action.to_tool_result_messages(results)
        )
        self._signal_consumer.emit_and_consume(signals, scope=scope)

    def _emit_phase_results(
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
            self._signal_consumer.emit_and_consume(signals, scope=scope)

    def _emit_note(
        self,
        note: JsonObject,
        *,
        scope: RunScope,
        cycle_id: str,
    ) -> None:
        self._signal_consumer.emit_and_consume(
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
