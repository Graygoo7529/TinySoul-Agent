"""
State module for TinySoul.

Provides runtime state management for the agent query loop,
including todo lists, milestones, action records, and error tracking.
"""

from tinysoul.trap import TodoAmbiguityError

from .action_record import ActionRecord, OngoingActionRecord
from .loop_error import LoopErrorItem, build_feedback_errors
from .state import QueryState
from .schema import get_query_state_schema
from .todo import TaskStatus, TodoItem
from .update import apply_state_updates

__all__ = [
    "QueryState",
    "TodoItem",
    "ActionRecord",
    "OngoingActionRecord",
    "TaskStatus",
    "TodoAmbiguityError",
    "LoopErrorItem",
    "build_feedback_errors",
    "get_query_state_schema",
    "apply_state_updates",
]
