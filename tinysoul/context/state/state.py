"""
QueryState Implementation for Query Loop.

Acts as a Facade over independent state components:
- TodoManager: todo_list operations
- MilestoneManager: milestone_list operations
- ActionRecordManager: action_record_list and ongoing_action_list operations
- LoopErrorManager: loop_error_list operations
"""

from typing import Any

from .action_record import ActionRecord, ActionRecordManager, OngoingActionRecord
from .loop_error import LoopErrorItem, LoopErrorManager
from .milestone import MilestoneManager
from .todo import TaskStatus, TodoItem, TodoManager


class QueryState:
    """
    State container for query loop.

    QueryState acts as a Facade over independent state managers.
    """

    def __init__(self, init_todo_list: list[TodoItem] | None = None):
        # Independent state managers
        self._todo_manager = TodoManager(init_todo_list)
        self._milestone_manager = MilestoneManager()
        self._action_record_manager = ActionRecordManager()
        self._error_manager = LoopErrorManager()

    # =====================================================================
    # Properties (backward compatible direct access)
    # ========================================================================

    @property
    def todo_list(self) -> list[TodoItem]:
        """Get all todo items."""
        return self._todo_manager.todo_list

    @property
    def milestone_list(self) -> list[str]:
        """Get list of all milestone descriptions."""
        return self._milestone_manager.milestone_list

    @property
    def action_record_list(self) -> list[ActionRecord]:
        """Get all action records."""
        return self._action_record_manager.action_record_list

    @property
    def ongoing_action_list(self) -> list[dict]:
        """Get list of currently running action executions."""
        return self._action_record_manager.ongoing_action_list

    @property
    def loop_error_list(self) -> list[LoopErrorItem]:
        """Get all loop error items."""
        return self._error_manager.loop_error_list

    # ========================================================================
    # Todo List Operations (delegate to TodoManager)
    # ========================================================================

    def add_todo(self, description: str, todo_id: str) -> TodoItem:
        """Add a new todo item."""
        return self._todo_manager.add(description, todo_id)

    def complete_todo(self, todo_id: str) -> TodoItem | None:
        """Mark a todo as completed."""
        return self._todo_manager.complete(todo_id)

    def cancel_todo(self, todo_id: str) -> TodoItem | None:
        """
        Cancel a todo item.

        Only pending todos can be cancelled.
        Completed or already cancelled todos cannot be cancelled.
        """
        return self._todo_manager.cancel(todo_id)

    def get_todo_list(self) -> list[TodoItem]:
        """Get all todo items."""
        return self._todo_manager.get_all()

    def get_todos(self, status: TaskStatus | None = None) -> list[TodoItem]:
        """
        Get todo items, optionally filtered by status.

        Args:
            status: Filter by status (PENDING, DONE, CANCELLED)
                   If None, return all todos.
        """
        return self._todo_manager.get_by_status(status)

    # ========================================================================
    # Milestone Operations (delegate to MilestoneManager)
    # ========================================================================

    def add_milestone(self, description: str) -> str:
        """Add a completed milestone description to the list."""
        return self._milestone_manager.add(description)

    def get_milestones(self) -> list[str]:
        """Get list of all milestone descriptions."""
        return self._milestone_manager.get_all()

    # ========================================================================
    # Action List Operations (delegate to ActionRecordManager)
    # ========================================================================

    def record_action(
        self,
        action_name: str,
        action_target: str,
        action_input: dict,
        action_result: dict,
        turn: int = 0,
        status: str = "success",
        execution_id: str = "",
    ) -> ActionRecord:
        """
        Record an executed action result.

        For both ongoing and single-run actions, each result produces
        a new ActionRecord. For ongoing actions with multiple results,
        call this method multiple times.
        """
        return self._action_record_manager.record(
            action_name=action_name,
            action_target=action_target,
            action_input=action_input,
            action_result=action_result,
            turn=turn,
            status=status,
            execution_id=execution_id,
        )

    def get_action_record_list(self) -> list[ActionRecord]:
        """Get all action records."""
        return self._action_record_manager.get_all()

    def peek_new_action_records(self) -> list[ActionRecord]:
        """
        Peek all unread action records without marking them as read.

        Returns:
            List of ActionRecord where read=False
        """
        return self._action_record_manager.peek_unread()

    def ack_action_records(self) -> None:
        """Mark all unread action records as read. Call after successful state update."""
        self._action_record_manager.mark_all_read()



    # ========================================================================
    # Ongoing Actions (delegate to ActionRecordManager)
    # ========================================================================

    def get_ongoing_action_list(self) -> list[dict]:
        """Get list of currently running action executions."""
        return self._action_record_manager.get_ongoing()

    def add_ongoing_action(
        self,
        execution_id: str,
        action_name: str,
        turn: int = 0,
        status: str = "running",
    ) -> OngoingActionRecord:
        """Add an ongoing action execution to tracking."""
        return self._action_record_manager.add_ongoing(
            execution_id=execution_id,
            action_name=action_name,
            turn=turn,
            status=status,
        )

    def remove_ongoing_action(self, execution_id: str) -> OngoingActionRecord | None:
        """Remove an ongoing action execution from tracking."""
        return self._action_record_manager.remove_ongoing(execution_id)

    # ========================================================================
    # Loop Error Operations (delegate to LoopErrorManager)
    # ========================================================================

    def add_loop_error(
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
        return self._error_manager.add(
            turn=turn,
            step=step,
            error_type=error_type,
            message=message,
            action_name=action_name,
            action_input=action_input,
            auto_handled=auto_handled,
            recovered=recovered,
            raw_traceback=raw_traceback,
        )

    def get_loop_error_list(self) -> list[LoopErrorItem]:
        """Get all loop error items."""
        return self._error_manager.get_all()
