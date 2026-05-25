"""Direct unit tests for ErrorTrap — the central exception router."""

from __future__ import annotations

import pytest

from tinysoul.trap import (
    ActionCancelledError,
    ActionExecutionError,
    ActionInputError,
    ConfigError,
    Disposition,
    ErrorContext,
    ErrorTrap,
    LLMResponseParseError,
    LLMTransientError,
    SystemExhaustedError,
    TodoAmbiguityError,
)
from tinysoul.trap.signal import SignalContext


class MockInterruptHandler:
    """Records TrapResult calls for test verification."""

    def __init__(self):
        self.calls: list = []

    def handle(self, trap_result, context: SignalContext) -> None:
        self.calls.append((trap_result, context))

    @property
    def last_trap_result(self):
        return self.calls[-1][0] if self.calls else None

    @property
    def last_loop_error(self):
        tr = self.last_trap_result
        return tr.loop_error if tr else None

    @property
    def last_action_result(self):
        tr = self.last_trap_result
        return tr.action_result if tr else None


class TestErrorTrapInterrupts:
    """OS-style interrupt routing."""

    def test_keyboard_interrupt_returns_user_interrupt_without_loop_error(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        outcome = trap.capture(
            KeyboardInterrupt(),
            ErrorContext(turn=2, step="choose_action"),
        )
        assert outcome.decision == Disposition.USER_INTERRUPT
        assert handler.last_loop_error is None


class TestErrorTrapAbortErrors:
    """Fatal errors that terminate the loop."""

    def test_config_error_returns_abort(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        outcome = trap.capture(
            ConfigError("missing api key"),
            ErrorContext(turn=1, step="choose_action"),
        )
        assert outcome.decision == Disposition.ABORT
        assert handler.last_loop_error is not None
        assert handler.last_loop_error.error_type == "ConfigError"
        assert handler.last_loop_error.step == "choose_action"

    def test_system_exhausted_error_returns_abort(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        outcome = trap.capture(
            SystemExhaustedError("all models down"),
            ErrorContext(turn=5, step="generate_parameters"),
        )
        assert outcome.decision == Disposition.ABORT
        assert handler.last_loop_error is not None
        assert handler.last_loop_error.error_type == "SystemExhaustedError"


class TestErrorTrapRecoverableErrors:
    """Errors that the system can handle automatically."""

    def test_llm_transient_error_becomes_system_exhausted_abort(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        outcome = trap.capture(
            LLMTransientError("timeout", model_name="glm-4"),
            ErrorContext(turn=2, step="choose_action"),
        )
        assert outcome.decision == Disposition.ABORT
        assert handler.last_loop_error is not None
        assert "SystemExhaustedError" in handler.last_loop_error.error_type
        assert "LLMTransientError" in handler.last_loop_error.error_type


class TestErrorTrapActionErrors:
    """Action execution errors are dual-recorded."""

    def test_action_execution_error_returns_next_step_with_dual_records(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        exc = ActionExecutionError("calc failed", action_name="calculate", action_input={"expr": "1/0"})
        outcome = trap.capture(
            exc,
            ErrorContext(turn=3, step="execute_action", action_name="calculate"),
        )
        assert outcome.decision == Disposition.NEXT_STEP
        assert handler.last_loop_error is not None
        assert handler.last_loop_error.error_type == "ActionExecutionError"
        assert handler.last_action_result is not None
        assert "calc failed" in handler.last_action_result["error"]

    def test_action_input_error_returns_next_step_with_dual_records(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        exc = ActionInputError("missing field", action_name="calculate", action_input={})
        outcome = trap.capture(
            exc,
            ErrorContext(turn=2, step="execute_action", action_name="calculate"),
        )
        assert outcome.decision == Disposition.NEXT_STEP
        assert handler.last_loop_error is not None
        assert handler.last_action_result is not None

    def test_error_type_chain_includes_cause(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        inner = ValueError("zero division")
        exc = ActionExecutionError("calc failed", action_name="calculate", action_input={})
        exc.__cause__ = inner
        trap.capture(
            exc,
            ErrorContext(turn=1, step="execute_action", action_name="calculate"),
        )
        assert handler.last_loop_error is not None
        assert handler.last_loop_error.error_type == "ActionExecutionError/ValueError"

    def test_action_cancelled_error_uses_cancelled_status(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        exc = ActionCancelledError(
            "stopped",
            action_name="calculate",
            action_input={"expr": "1+1"},
        )
        trap.capture(
            exc,
            ErrorContext(turn=1, step="execute_action", action_name="calculate"),
        )
        assert handler.last_trap_result.status == "cancelled"
        assert handler.last_action_result is not None


class TestErrorTrapStateErrors:
    """State operation errors are single-recorded (no action_result)."""

    def test_todo_ambiguity_error_returns_next_step_single_record(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        outcome = trap.capture(
            TodoAmbiguityError("ambiguous key 'verify'"),
            ErrorContext(turn=4, step="update_state"),
        )
        assert outcome.decision == Disposition.NEXT_STEP
        assert handler.last_loop_error is not None
        assert handler.last_action_result is None
        assert handler.last_loop_error.error_type == "TodoAmbiguityError"


class TestErrorTrapFeedbackErrors:
    """Generic feedback errors (non-action, non-state)."""

    def test_llm_response_parse_error_returns_next_step_single_record(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        outcome = trap.capture(
            LLMResponseParseError("bad json"),
            ErrorContext(turn=2, step="generate_parameters"),
        )
        assert outcome.decision == Disposition.NEXT_STEP
        assert handler.last_loop_error is not None
        assert handler.last_action_result is None

    def test_unknown_exception_wrapped_as_feedback_error(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        outcome = trap.capture(
            ZeroDivisionError("division by zero"),
            ErrorContext(turn=1, step="execute_action", action_name="calculate"),
        )
        assert outcome.decision == Disposition.NEXT_STEP
        assert handler.last_loop_error is not None
        assert "FeedbackError" in handler.last_loop_error.error_type
        assert "ZeroDivisionError" in handler.last_loop_error.error_type


class TestErrorTrapAutoHandledSemantics:
    """auto_handled errors suppress traceback and are marked accordingly."""

    def test_non_auto_handled_has_raw_traceback(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        try:
            raise ActionExecutionError("fail")
        except ActionExecutionError as exc:
            trap.capture(
                exc,
                ErrorContext(turn=1, step="execute_action"),
            )
        assert handler.last_loop_error is not None
        assert handler.last_loop_error.auto_handled is False
        assert handler.last_loop_error.raw_traceback is not None
        assert "Traceback" in handler.last_loop_error.raw_traceback


class TestErrorTrapErrorContextBinding:
    """ErrorContext fields are correctly bound to LoopErrorItem."""

    def test_turn_and_step_are_recorded(self):
        handler = MockInterruptHandler()
        trap = ErrorTrap(interrupt_handler=handler)
        trap.capture(
            ActionExecutionError("fail"),
            ErrorContext(turn=7, step="execute_action", action_name="bash"),
        )
        assert handler.last_loop_error is not None
        assert handler.last_loop_error.turn == 7
        assert handler.last_loop_error.step == "execute_action"
        assert handler.last_loop_error.action_name == "bash"
