"""
OS-Style Interrupt Controller for TinySoul.

ErrorTrap is the central interrupt vector table (IVT). All entry points
(capture / route / process_signal_batch) return a unified Outcome.
State side effects are executed internally via InterruptHandler;
 callers never interact with InterruptHandler directly.

Entry points (all return Outcome):
  1. capture(exc, context)       — external hard interrupt (BaseException)
  2. route(signal)               — internal soft interrupt (Signal)
  3. process_signal_batch(signals) — batch soft interrupt processing

Loop consumption model:
  - capture()      → Outcome (ABORT stops step, NEXT_STEP continues)
  - process_batch() → Outcome (COMPLETE_LOOP / SUSPEND_LOOP / NEXT_TURN / NEXT_STEP)

All state mutations happen inside ErrorTrap via the injected InterruptHandler.
"""

import traceback
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from tinysoul.context.state.loop_error import LoopErrorItem

from .exceptions import (
    AbortError,
    ActionError,
    FeedbackError,
    LLMTransientError,
    RecoverableError,
    TinysoulError,
)
from .signal import Signal, SignalContext, SignalType


class Disposition(Enum):
    """Unified execution control decision — used both internally and in Outcome."""

    ABORT = "abort"                    # Fatal: stop execution
    USER_INTERRUPT = "user_interrupt"  # User pressed Ctrl+C
    COMPLETE_LOOP = "complete_loop"    # Finish the loop
    SUSPEND_LOOP = "suspend_loop"      # Suspend the loop
    NEXT_TURN = "next_turn"            # Skip Step 3, next turn
    NEXT_STEP = "next_step"            # Normal continuation


@dataclass
class TrapOutcome:
    """
    Unified output of all ErrorTrap entry points.

    Loop consumes this to decide control flow.
    All state side effects have already been executed internally.
    """

    decision: Disposition


@dataclass
class ErrorContext:
    """Runtime context where the error occurred."""

    turn: int
    step: str
    action_name: str | None = None
    action_input: dict | None = None


@dataclass
class TrapResult:
    """Internal transport protocol between ErrorTrap and InterruptHandler."""

    disposition: Disposition
    loop_error: LoopErrorItem | None = None
    action_result: dict | None = None
    status: str = "success"


class ErrorTrap:
    """OS-Style Interrupt Controller.

    Three entry points (all return Outcome):
      - capture(exc, context): hard interrupt
      - route(signal): single soft interrupt
      - process_signal_batch(signals): batch soft interrupt

    InterruptHandler is injected at construction time and never exposed.
    """

    def __init__(
        self,
        ai_client: Any | None = None,
        query_state: Any | None = None,
        query_context: Any | None = None,
        logger: Any | None = None,
        interrupt_handler: Any | None = None,
    ):
        self._ai_client = ai_client

        if interrupt_handler is not None:
            self._interrupt_handler = interrupt_handler
        elif query_state is not None:
            from .interrupt_handler import InterruptHandler

            self._interrupt_handler = InterruptHandler(
                query_state=query_state,
                query_context=query_context,
                logger=logger,
            )
        else:
            self._interrupt_handler = None

    def _execute_handler(self, trap_result: TrapResult, context: SignalContext) -> None:
        """Execute state side effects via the internal InterruptHandler."""
        if self._interrupt_handler is not None:
            self._interrupt_handler.handle(trap_result, context)

    # ====================================================================
    # Entry 1: External hard interrupt (BaseException)
    # ====================================================================

    def capture(self, exc: BaseException, context: ErrorContext) -> TrapOutcome:
        """
        Capture an external exception, route through IVT, execute state side effects,
        return unified Outcome.
        """
        if isinstance(exc, SystemExit):
            raise exc

        trap_result = self._route_exception(exc, context)

        signal_ctx = SignalContext(
            turn=context.turn,
            step=context.step,
            action_name=context.action_name,
            action_input=context.action_input,
        )
        self._execute_handler(trap_result, signal_ctx)

        return TrapOutcome(decision=trap_result.disposition)

    def _route_exception(self, exc: BaseException, context: ErrorContext) -> TrapResult:
        """Route a BaseException through the IVT."""
        if isinstance(exc, FeedbackError):
            context = ErrorContext(
                turn=context.turn,
                step=context.step,
                action_name=exc.action_name or context.action_name,
                action_input=exc.action_input or context.action_input,
            )

        error_type = type(exc).__name__
        if exc.__cause__:
            error_type = f"{error_type}/{type(exc.__cause__).__name__}"

        message = (
            exc.to_loop_error_message()
            if isinstance(exc, FeedbackError)
            else str(exc)
        )

        if isinstance(exc, KeyboardInterrupt):
            return self._handle_interrupt(
                context,
                is_keyboard=True,
                error_type=error_type,
                message=message,
            )

        if isinstance(exc, TinysoulError):
            if isinstance(exc, AbortError):
                return self._handle_abort(
                    error_type, message, context,
                    raw_traceback=traceback.format_exc(),
                )

            if isinstance(exc, RecoverableError):
                if isinstance(exc, LLMTransientError):
                    fatal_type = f"SystemExhaustedError/{error_type}"
                    fatal_message = f"All AI models exhausted. Last: {message}"
                    return self._handle_abort(
                        fatal_type, fatal_message, context,
                        raw_traceback=traceback.format_exc(),
                    )

                return self._handle_recoverable(error_type, message, context)

            if isinstance(exc, FeedbackError):
                return self._handle_feedback(
                    error_type=error_type,
                    message=message,
                    context=context,
                    is_action_error=isinstance(exc, ActionError),
                    raw_traceback=traceback.format_exc(),
                )

            return self._handle_feedback(
                error_type=error_type,
                message=message,
                context=context,
                raw_traceback=traceback.format_exc(),
            )

        return self._handle_feedback(
            error_type=f"FeedbackError/{error_type}",
            message=f"Unexpected error: {exc}",
            context=context,
            raw_traceback=traceback.format_exc(),
        )

    # ====================================================================
    # Entry 2: Internal soft interrupt (Signal) — single
    # ====================================================================

    _SIGNAL_FAILURE_MAP: dict[SignalType, tuple[str, str, bool]] = {
        SignalType.ACTION_TIMEOUT: ("ActionTimeoutError", "Action timed out", True),
        SignalType.ACTION_CANCELLED: ("ActionCancelledError", "Action cancelled", True),
    }

    _CONTROL_FLOW: dict[SignalType, Disposition] = {
        SignalType.LOOP_COMPLETE: Disposition.COMPLETE_LOOP,
        SignalType.LOOP_NEXT_TURN: Disposition.NEXT_TURN,
        SignalType.LOOP_SUSPEND: Disposition.SUSPEND_LOOP,
    }

    _SUCCESS_SIGNALS: set[SignalType] = {
        SignalType.ACTION_COMPLETED,
        SignalType.ONGOING_STARTED,
        SignalType.ONGOING_TICK,
        SignalType.ONGOING_COMPLETED,
    }

    def route(self, signal: Signal) -> TrapOutcome:
        """Route an internal Signal through the IVT, execute side effects, return Outcome."""
        context = ErrorContext(
            turn=signal.turn,
            step=signal.step or "execute_action",
            action_name=signal.action_name,
            action_input=signal.action_input,
        )

        if signal.type in self._CONTROL_FLOW:
            trap_result = TrapResult(
                self._CONTROL_FLOW[signal.type],
                loop_error=None,
                action_result=None,
                status="success",
            )
            self._execute_handler(trap_result, signal.to_error_context())
            return TrapOutcome(decision=trap_result.disposition)

        if signal.type in self._SUCCESS_SIGNALS:
            trap_result = TrapResult(
                Disposition.NEXT_STEP,
                loop_error=None,
                action_result=signal.payload.get("result", {}),
                status="success",
            )
            self._execute_handler(trap_result, signal.to_error_context())
            return TrapOutcome(decision=trap_result.disposition)

        if signal.type == SignalType.ACTION_FAILED:
            trap_result = self._handle_feedback(
                error_type=signal.payload.get("error_type", "FeedbackError"),
                message=signal.payload.get("error", "Action failed"),
                context=context,
                is_action_error=True,
            )
            self._execute_handler(trap_result, signal.to_error_context())
            return TrapOutcome(decision=trap_result.disposition)

        if signal.type == SignalType.ACTION_CANCELLED:
            trap_result = self._handle_feedback(
                error_type=signal.payload.get("error_type", "ActionCancelledError"),
                message=signal.payload.get("error", "Action cancelled"),
                context=context,
                is_action_error=True,
            )
            self._execute_handler(trap_result, signal.to_error_context())
            return TrapOutcome(decision=trap_result.disposition)

        if signal.type == SignalType.USER_APPEND:
            trap_result = TrapResult(
                Disposition.NEXT_STEP,
                loop_error=None,
                action_result=None,
                status="success",
            )
            self._execute_handler(trap_result, signal.to_error_context())
            return TrapOutcome(decision=trap_result.disposition)

        mapping = self._SIGNAL_FAILURE_MAP.get(signal.type)
        if mapping is not None:
            error_type, default_msg, is_action_error = mapping
            trap_result = self._handle_feedback(
                error_type=error_type,
                message=signal.payload.get("error", default_msg),
                context=context,
                is_action_error=is_action_error,
            )
            self._execute_handler(trap_result, signal.to_error_context())
            return TrapOutcome(decision=trap_result.disposition)

        return TrapOutcome(decision=Disposition.NEXT_STEP)

    # ====================================================================
    # Entry 3: Batch soft interrupt processing
    # ====================================================================

    def process_signal_batch(self, signals: list[Signal]) -> TrapOutcome:
        """
        Batch-process signals: execute data side effects, aggregate control flow.
        Returns unified TrapOutcome.

        Priority:
          1. LOOP_COMPLETE   → COMPLETE_LOOP (highest control)
          2. LOOP_SUSPEND    → SUSPEND_LOOP
          3. Success data + LOOP_NEXT_TURN → NEXT_STEP (keep current turn if data succeeded)
          4. LOOP_NEXT_TURN  → NEXT_TURN
          5. (default)       → NEXT_STEP
        """
        control_signals = [s for s in signals if s.type in self._CONTROL_FLOW]
        data_signals = [s for s in signals if s.type not in self._CONTROL_FLOW]

        for signal in data_signals:
            self.route(signal)

        if not control_signals:
            return TrapOutcome(decision=Disposition.NEXT_STEP)

        control_types = {s.type for s in control_signals}

        if SignalType.LOOP_COMPLETE in control_types:
            return TrapOutcome(decision=Disposition.COMPLETE_LOOP)

        if SignalType.LOOP_SUSPEND in control_types:
            return TrapOutcome(decision=Disposition.SUSPEND_LOOP)

        if SignalType.LOOP_NEXT_TURN in control_types:
            return TrapOutcome(decision=Disposition.NEXT_TURN)

        return TrapOutcome(decision=Disposition.NEXT_STEP)

    # ====================================================================
    # IVT handlers
    # ====================================================================

    def _handle_interrupt(
        self,
        context: ErrorContext,
        is_keyboard: bool,
        error_type: str,
        message: str,
    ) -> TrapResult:
        if is_keyboard:
            return TrapResult(Disposition.USER_INTERRUPT, loop_error=None)

        return TrapResult(
            Disposition.NEXT_STEP,
            loop_error=self._build_loop_error(
                error_type, message, context, auto_handled=True
            ),
        )

    def _handle_abort(
        self,
        error_type: str,
        message: str,
        context: ErrorContext,
        raw_traceback: str | None = None,
    ) -> TrapResult:
        return TrapResult(
            Disposition.ABORT,
            loop_error=self._build_loop_error(
                error_type, message, context, raw_traceback=raw_traceback
            ),
        )

    def _handle_recoverable(
        self, error_type: str, message: str, context: ErrorContext
    ) -> TrapResult:
        return TrapResult(
            Disposition.NEXT_STEP,
            loop_error=self._build_loop_error(
                error_type, message, context, auto_handled=True
            ),
        )

    def _handle_feedback(
        self,
        *,
        error_type: str,
        message: str,
        context: ErrorContext,
        is_action_error: bool = False,
        raw_traceback: str | None = None,
    ) -> TrapResult:
        loop_error = self._build_loop_error(
            error_type, message, context, raw_traceback=raw_traceback
        )
        action_result = None
        status = "success"
        if is_action_error:
            action_result = {"error": message, "error_type": error_type}
            lowered = error_type.lower()
            if "timeout" in lowered:
                status = "timeout"
            elif "cancel" in lowered:
                status = "cancelled"
            else:
                status = "failed"

        return TrapResult(
            Disposition.NEXT_STEP,
            loop_error=loop_error,
            action_result=action_result,
            status=status,
        )

    def _build_loop_error(
        self,
        error_type: str,
        message: str,
        context: ErrorContext,
        auto_handled: bool = False,
        recovered: bool = False,
        raw_traceback: str | None = None,
    ) -> LoopErrorItem:
        return LoopErrorItem(
            timestamp=datetime.now(),
            turn=context.turn,
            step=context.step,
            error_type=error_type,
            message=message,
            action_name=context.action_name,
            action_input=context.action_input,
            auto_handled=auto_handled,
            recovered=recovered,
            raw_traceback=raw_traceback,
        )
