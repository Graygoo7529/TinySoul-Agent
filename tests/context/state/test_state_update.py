"""Tests for apply_state_updates pure function."""

from __future__ import annotations

import pytest

from tinysoul.context.state import QueryState, TaskStatus
from tinysoul.context.state.update import apply_state_updates


class TestApplyStateUpdates:
    """Verify that apply_state_updates correctly mutates QueryState
    and handles failures by recording loop errors rather than raising."""

    def test_todo_add_success(self):
        state = QueryState()
        updates = {
            "todo_operations": [
                {"operation": "add", "key": "verify", "description": "Verify result"}
            ],
            "milestone_operation": "no-change",
            "milestone_param": None,
        }
        apply_state_updates(state, updates, turn=1)

        assert len(state.todo_list) == 1
        assert state.todo_list[0].semantic_key == "verify"
        assert state.todo_list[0].description == "Verify result"
        assert state.todo_list[0].status == TaskStatus.PENDING

    def test_todo_complete_success(self):
        state = QueryState()
        state.add_todo("Do something", "task1")
        updates = {
            "todo_operations": [{"operation": "complete", "key": "task1"}],
            "milestone_operation": "no-change",
            "milestone_param": None,
        }
        apply_state_updates(state, updates, turn=1)

        assert state.todo_list[0].status == TaskStatus.DONE

    def test_todo_cancel_success(self):
        state = QueryState()
        state.add_todo("Do something", "task1")
        updates = {
            "todo_operations": [{"operation": "cancel", "key": "task1"}],
            "milestone_operation": "no-change",
            "milestone_param": None,
        }
        apply_state_updates(state, updates, turn=1)

        assert state.todo_list[0].status == TaskStatus.CANCELLED

    def test_todo_complete_missing_key_ignored(self):
        state = QueryState()
        updates = {
            "todo_operations": [{"operation": "complete", "key": "nonexistent"}],
            "milestone_operation": "no-change",
            "milestone_param": None,
        }
        apply_state_updates(state, updates, turn=1)

        assert len(state.todo_list) == 0
        assert len(state.loop_error_list) == 0

    def test_todo_cancel_missing_key_ignored(self):
        state = QueryState()
        updates = {
            "todo_operations": [{"operation": "cancel", "key": "nonexistent"}],
            "milestone_operation": "no-change",
            "milestone_param": None,
        }
        apply_state_updates(state, updates, turn=1)

        assert len(state.todo_list) == 0
        assert len(state.loop_error_list) == 0

    def test_milestone_add_success(self):
        state = QueryState()
        updates = {
            "todo_operations": [],
            "milestone_operation": "add",
            "milestone_param": "Reached checkpoint A",
        }
        apply_state_updates(state, updates, turn=1)

        assert state.milestone_list == ["Reached checkpoint A"]

    def test_todo_operation_failure_records_loop_error(self):
        state = QueryState()
        # Two todos with the same semantic key create ambiguity on complete.
        state.add_todo("First", "task")
        state.add_todo("Second", "task")
        updates = {
            "todo_operations": [{"operation": "complete", "key": "task"}],
            "milestone_operation": "no-change",
            "milestone_param": None,
        }
        apply_state_updates(state, updates, turn=2)

        # Failure is recorded as a loop error rather than raised.
        assert len(state.loop_error_list) == 1
        assert state.loop_error_list[0].step == "update_state"
        assert "TodoAmbiguityError" in state.loop_error_list[0].error_type
        # Both todos remain PENDING because the operation failed.
        assert all(t.status == TaskStatus.PENDING for t in state.todo_list)

    def test_invalid_milestone_operation_ignored(self):
        state = QueryState()
        updates = {
            "todo_operations": [],
            "milestone_operation": "invalid-op",
            "milestone_param": "something",
        }
        apply_state_updates(state, updates, turn=1)

        # Unknown operation is silently ignored.
        assert len(state.milestone_list) == 0
        assert len(state.loop_error_list) == 0

    def test_multiple_todo_operations_partial_failure(self):
        state = QueryState()
        state.add_todo("Task A", "a")
        updates = {
            "todo_operations": [
                {"operation": "complete", "key": "a"},
                {"operation": "complete", "key": "missing"},  # ignored, no error
            ],
            "milestone_operation": "no-change",
            "milestone_param": None,
        }
        apply_state_updates(state, updates, turn=1)

        assert state.todo_list[0].status == TaskStatus.DONE
        assert len(state.loop_error_list) == 0

    def test_logger_events_emitted(self, capture_logger):
        logger, sink = capture_logger
        state = QueryState()
        state.add_todo("Task", "t1")
        updates = {
            "todo_operations": [
                {"operation": "add", "key": "t2", "description": "Todo 2"},
                {"operation": "complete", "key": "t1"},
            ],
            "milestone_operation": "add",
            "milestone_param": "Milestone 1",
        }
        apply_state_updates(state, updates, turn=1, logger=logger)

        titles = [e.title for e in sink.events]
        assert any("todo_added" in t for t in titles)
        assert any("todo_completed" in t for t in titles)
        assert any("milestone_added" in t for t in titles)
