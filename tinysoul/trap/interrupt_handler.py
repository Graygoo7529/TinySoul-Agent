"""
Interrupt Handler — the execution arm of ErrorTrap.

Receives TrapResult from ErrorTrap (the OS-style interrupt controller) and
carries out the actual state mutations: writing to action_record_list,
loop_error_list, and ongoing_action_list.

This separation keeps ErrorTrap focused on decision-making (Disposition)
while InterruptHandler handles all state side effects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .signal import SignalContext, SignalType
from .trap import Disposition, TrapResult

if TYPE_CHECKING:
    from tinysoul.infra import EventLogger
    from tinysoul.context.state import QueryState


class InterruptHandler:
    """
    Execution arm of the interrupt controller.

    Responsibilities:
    1. Write action_record_list entries (success, failure, ONGOING tick)
    2. Write loop_error_list entries (for failures)
    3. Maintain ongoing_action_list (for ONGOING lifecycle)
    4. Emit structured log events
    """

    def __init__(
        self,
        query_state: QueryState,
        query_context: Any | None = None,
        logger: EventLogger | None = None,
    ):
        self._state = query_state
        self._context = query_context
        self._logger = logger

    def handle(self, trap_result: TrapResult, context: SignalContext) -> None:
        """
        Execute the TrapResult's instructions against QueryState and QueryContext.

        This is the single entry point for all state mutations triggered
        by ErrorTrap's interrupt vector table.
        """
        # 1. Handle user dialogue append
        if context.signal_type == SignalType.USER_APPEND:
            self._append_query_events(context)
            return

        # 2. Write action record (success or failure)
        if trap_result.action_result is not None:
            self._write_action_record(trap_result, context)

        # 3. Write loop error (for failures)
        if trap_result.loop_error is not None:
            self._write_loop_error(trap_result, context)

        # 4. Update ONGOING lifecycle
        if context.signal_type and context.signal_type.value.startswith("ongoing_"):
            self._update_ongoing_lifecycle(context)

        # 5. Log step failure (for non-auto-handled errors)
        if (
            trap_result.loop_error is not None
            and not trap_result.loop_error.auto_handled
            and self._logger is not None
        ):
            self._logger.step_failed(
                turn=trap_result.loop_error.turn,
                step=trap_result.loop_error.step,
                error=trap_result.loop_error.message,
                disposition=trap_result.disposition.value,
            )

    def _append_query_events(self, context: SignalContext) -> None:
        """Append a user message to QueryEvents via QueryContext."""
        if self._context is None:
            return
        content = context.payload.get("content", "") if context.payload else ""
        if content:
            self._context.append_append(content, turn=context.turn)

    def _write_action_record(
        self, trap_result: TrapResult, context: SignalContext
    ) -> None:
        """Write an ActionRecord based on TrapResult.action_result."""
        result = trap_result.action_result or {}
        action_target = ""
        if context.payload:
            action_target = context.payload.get("target", "")
        if not action_target and isinstance(result, dict):
            action_target = result.get("target", "")

        self._state.record_action(
            action_name=context.action_name or "",
            action_target=action_target,
            action_input=context.action_input or {},
            action_result=result,
            turn=context.turn,
            status=trap_result.status,
            execution_id=context.execution_id or "",
        )

        if self._logger is not None:
            self._logger.action_result(
                result=result,
                success=trap_result.status == "success",
                action_name=context.action_name or "",
            )

    def _write_loop_error(
        self, trap_result: TrapResult, context: SignalContext
    ) -> None:
        """Write a LoopErrorItem based on TrapResult.loop_error."""
        err = trap_result.loop_error
        if err is None:
            return

        self._state.add_loop_error(
            turn=err.turn,
            step=err.step,
            error_type=err.error_type,
            message=err.message,
            action_name=err.action_name,
            action_input=err.action_input,
            auto_handled=err.auto_handled,
            recovered=err.recovered,
            raw_traceback=err.raw_traceback,
        )

        if self._logger is not None and not err.auto_handled:
            self._logger.step_failed_detail(
                turn=err.turn,
                step=err.step,
                error_type=err.error_type,
                message=err.message,
                raw_traceback=err.raw_traceback or "",
            )

    def _update_ongoing_lifecycle(self, context: SignalContext) -> None:
        """Update ongoing_action_list based on ONGOING signal type."""
        signal_type = context.signal_type
        action_name = context.action_name
        execution_id = context.execution_id

        if action_name is None or not execution_id:
            return

        if signal_type == SignalType.ONGOING_STARTED:
            self._state.add_ongoing_action(
                execution_id=execution_id,
                action_name=action_name,
                turn=context.turn,
            )

        elif signal_type == SignalType.ONGOING_COMPLETED:
            self._state.remove_ongoing_action(execution_id)
