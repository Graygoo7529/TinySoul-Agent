"""Loop phase execution units."""

from __future__ import annotations


from tinysoul.kernel.action import ActionEngine, ActionError
from tinysoul.kernel.context import (
    ContextEngine,
    ControlResult,
    build_trace_phase_note_signal,
)
from tinysoul.kernel.context.errors import ContextError
from tinysoul.infra.json import JsonObject
from tinysoul.llm.protocol.requests import ModelContextOverflowPolicy, TaskCall
from tinysoul.llm.protocol.responses import TaskResultStatus
from tinysoul.runtime import CyclePhase, RunScope, SignalBus
from tinysoul.kernel.action.runtime_bridge import RuntimeActionBridge
from tinysoul.kernel.context.runtime_bridge import RuntimeContextBridge
from tinysoul.kernel.loop.runtime_bridge import RuntimeLoopBridge

from ..interaction.cancellation import TurnCancellation
from ..context_signals import ContextSignalConsumer
from ..errors import LoopError
from ..prompts import phase1_task_prompt
from ..signals import LoopTraceNoteKind

from .contracts import LLMRunner, PhaseFailure, Phase1Outcome
from .tasks import (
    _merge_tool_scopes,
    _required_tool_settings,
    _turn_task_cancellation,
    _task_result_feedback,
    _control_result_payload,
)


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
        self._context.mark_model_consumed(messages)
        if result.status is TaskResultStatus.FAILURE:
            return await self._failed(
                scope=scope,
                cycle_id=cycle_id,
                reason="framework_task_failure",
                feedback=(_task_result_feedback(result),),
            )

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
            consume_results = await self._signal_consumer.emit_and_consume(
                normalization.signals,
                scope=scope,
            )
        except ContextError as exc:
            raise self._context_bridge.from_context_error(exc) from exc
        control_results = (*normalization.results, *consume_results)
        if control_results:
            (
                await self._emit_phase_note(
                    {
                        "kind": LoopTraceNoteKind.PHASE1_CONTROL_FEEDBACK.value,
                        "results": [
                            _control_result_payload(result)
                            for result in control_results
                        ],
                    },
                    scope=scope,
                    cycle_id=cycle_id,
                )
            )
        feedback = selection.feedback or (
            ("Phase1 did not select any action domain.",)
            if not selection.selected_domains
            else ()
        )
        if feedback:
            return await self._failed(
                scope=scope,
                cycle_id=cycle_id,
                reason="invalid_domain_selection",
                feedback=tuple(feedback),
                control_results=control_results,
            )
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
        (
            await self._emit_phase_note(
                {
                    "kind": LoopTraceNoteKind.PHASE1_TASK_FAILED.value,
                    "reason": reason,
                    "feedback": list(feedback),
                },
                scope=scope,
                cycle_id=cycle_id,
            )
        )
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
        (
            await self._signal_consumer.emit_and_consume(
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
        )
