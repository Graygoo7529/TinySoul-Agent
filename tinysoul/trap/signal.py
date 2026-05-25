"""
Signal system for TinySoul.

Signal is the unified primitive for all execution events in the query loop.
It serves as the "soft interrupt" counterpart to BaseException "hard interrupts",
both routed through ErrorTrap's interrupt vector table.

Signal Types:
  - Action signals: ACTION_COMPLETED, ACTION_FAILED, ACTION_TIMEOUT, ACTION_CANCELLED
  - ONGOING signals: ONGOING_STARTED, ONGOING_TICK, ONGOING_COMPLETED
  - Loop control flow signals: LOOP_COMPLETE, LOOP_NEXT_TURN, LOOP_SUSPEND
  - User dialogue signals: USER_APPEND

Architecture:
  Action/Step execution
      ↓
  Success / Failure / Timeout / Cancellation / Tick / UserAppend
      ↓
  Signal (unified format)
      ↓
  ErrorTrap.route(signal)  ← soft interrupt entry
      ↓
  Data signals → InterruptHandler → QueryState / QueryContext
  Control signals → aggregated → TrapOutcome → QueryLoop
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class SignalType(StrEnum):
    """Signal type enumeration — the soft interrupt vector numbers."""

    # ── Action execution signals ──
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    ACTION_TIMEOUT = "action_timeout"
    ACTION_CANCELLED = "action_cancelled"

    # ── ONGOING lifecycle signals ──
    ONGOING_STARTED = "ongoing_started"
    ONGOING_TICK = "ongoing_tick"
    ONGOING_COMPLETED = "ongoing_completed"

    # ── Loop control flow signals (control decisions, NO data) ──
    LOOP_COMPLETE = "loop_complete"
    LOOP_NEXT_TURN = "loop_next_turn"
    LOOP_SUSPEND = "loop_suspend"

    # ── User dialogue signals ──
    USER_APPEND = "user_append"


@dataclass
class Signal:
    """
    Unified signal format for all execution events.

    Signal is the "soft interrupt" that flows through the same routing
    infrastructure as BaseException "hard interrupts".
    """

    type: SignalType
    turn: int
    step: str | None = None
    action_name: str | None = None
    action_input: dict | None = None
    execution_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_error_context(self) -> "SignalContext":
        """Convert to SignalContext for ErrorTrap routing."""
        return SignalContext(
            turn=self.turn,
            step=self.step or "execute_action",
            action_name=self.action_name,
            action_input=self.action_input,
            execution_id=self.execution_id,
            signal_type=self.type,
            payload=self.payload,
        )


@dataclass
class SignalContext:
    """
    Runtime context for signal routing — the soft-interrupt counterpart to ErrorContext.

    Mirrors ErrorContext's shape for uniform handling in ErrorTrap and InterruptHandler.
    """

    turn: int
    step: str
    action_name: str | None = None
    action_input: dict | None = None
    execution_id: str | None = None
    signal_type: SignalType | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class SignalBus:
    """
    Signal bus — the single source of truth for all execution events.

    Receives Signals from parallel/ongoing/async execution and queues them
    for consumption by the query loop's Step 3.
    """

    def __init__(self):
        self._signals: list[Signal] = []
        self._lock = threading.Lock()

    def emit(self, signal: Signal) -> None:
        """Emit a signal to the bus."""
        with self._lock:
            self._signals.append(signal)

    def consume(self) -> list[Signal]:
        """Consume all pending signals and clear the bus."""
        with self._lock:
            consumed = list(self._signals)
            self._signals.clear()
            return consumed

    def peek(self) -> list[Signal]:
        """Peek at pending signals without consuming."""
        with self._lock:
            return list(self._signals)

    def __len__(self) -> int:
        with self._lock:
            return len(self._signals)
