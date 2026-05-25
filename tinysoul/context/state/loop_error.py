"""
LoopError component for Query State.

Provides LoopErrorItem dataclass, LoopErrorManager, and feedback view helpers.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class LoopErrorItem:
    """Unified error record for the audit trail (loop_error_list).

    Feedback to the LLM is derived from this via to_feedback_view().
    """

    timestamp: datetime
    turn: int
    step: str
    error_type: str  # e.g. "ActionError/ActionExecutionError/ValueError"
    message: str
    action_name: str | None = None
    action_input: dict | None = None
    auto_handled: bool = False
    recovered: bool = False
    raw_traceback: str | None = None

    def to_feedback_view(self) -> dict[str, Any]:
        """Extract the LLM-facing view from this error record."""
        view: dict[str, Any] = {
            "turn": self.turn,
            "step": self.step,
            "error_type": self.error_type,
            "message": self.message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
        if self.action_name:
            view["action_name"] = self.action_name
        if self.action_input:
            view["action_input"] = self.action_input
        return view


class LoopErrorManager:
    """Manages loop error records."""

    def __init__(self):
        self._loop_error_list: list[LoopErrorItem] = []

    @property
    def loop_error_list(self) -> list[LoopErrorItem]:
        """Return a copy of the loop error list."""
        return self._loop_error_list.copy()

    def add(
        self,
        turn: int,
        step: str,
        error_type: str,
        message: str,
        action_name: str | None = None,
        action_input: dict | None = None,
        auto_handled: bool = False,
        recovered: bool = False,
        raw_traceback: str | None = None,
    ) -> LoopErrorItem:
        """Record a query loop execution error."""
        item = LoopErrorItem(
            turn=turn,
            step=step,
            error_type=error_type,
            message=message,
            action_name=action_name,
            action_input=action_input,
            auto_handled=auto_handled,
            recovered=recovered,
            raw_traceback=raw_traceback,
            timestamp=datetime.now(),
        )
        self._loop_error_list.append(item)
        return item

    def get_all(self) -> list[LoopErrorItem]:
        """Get all loop error items."""
        return self._loop_error_list.copy()


def build_feedback_errors(
    loop_errors: list[LoopErrorItem],
) -> list[dict[str, Any]]:
    """Extract LLM-facing feedback views from a list of LoopErrorItems.

    Auto-handled errors are suppressed (the LLM doesn't need to know about
    errors that were already fixed automatically).
    """
    result = []
    for item in loop_errors:
        if item.auto_handled:
            continue
        result.append(item.to_feedback_view())
    return result
