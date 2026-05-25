"""Unit tests for TodoManager — dual key system, ambiguity, normalization."""

from __future__ import annotations

import pytest

from tinysoul.trap import StateError, TodoAmbiguityError
from tinysoul.context.state import QueryState, TaskStatus
from tinysoul.context.state.todo import TodoItem, TodoManager


class TestTodoAdd:
    def test_add_creates_pending_item(self):
        mgr = TodoManager()
        todo = mgr.add("Test task", "test_task")
        assert isinstance(todo, TodoItem)
        assert todo.description == "Test task"
        assert todo.status == TaskStatus.PENDING
        assert todo.semantic_key == "test_task"
        assert todo.display_key == "test_task-1"
        assert len(todo.id) == 8
        assert todo.completed_at is None

    def test_add_normalizes_key(self):
        mgr = TodoManager()
        todo = mgr.add("Task", "VERIFY-RESULT")
        assert todo.semantic_key == "verify_result"
        assert todo.display_key == "verify_result-1"

    def test_add_with_spaces_and_hyphens(self):
        mgr = TodoManager()
        todo = mgr.add("Task", "verify result")
        assert todo.semantic_key == "verify_result"

    def test_add_empty_key_raises(self):
        mgr = TodoManager()
        with pytest.raises(StateError, match="semantic_key is required"):
            mgr.add("Task", "")

    def test_sequential_display_keys(self):
        mgr = TodoManager()
        t1 = mgr.add("A", "verify")
        t2 = mgr.add("B", "verify")
        assert t1.display_key == "verify-1"
        assert t2.display_key == "verify-2"


class TestTodoComplete:
    def test_complete_by_display_key(self):
        mgr = TodoManager()
        todo = mgr.add("Task", "verify")
        result = mgr.complete(todo.display_key)
        assert result is not None
        assert result.status == TaskStatus.DONE
        assert result.completed_at is not None

    def test_complete_by_semantic_key_when_unique(self):
        mgr = TodoManager()
        mgr.add("Task", "verify")
        result = mgr.complete("verify")
        assert result is not None
        assert result.status == TaskStatus.DONE

    def test_complete_returns_none_for_nonexistent(self):
        mgr = TodoManager()
        assert mgr.complete("nonexistent") is None

    def test_complete_returns_none_for_already_done(self):
        mgr = TodoManager()
        todo = mgr.add("Task", "verify")
        mgr.complete(todo.display_key)
        assert mgr.complete(todo.display_key) is None

    def test_complete_ambiguity_raises(self):
        mgr = TodoManager()
        mgr.add("Task A", "verify")
        mgr.add("Task B", "verify")
        with pytest.raises(TodoAmbiguityError, match="Ambiguous todo key 'verify'"):
            mgr.complete("verify")


class TestTodoCancel:
    def test_cancel_pending_todo(self):
        mgr = TodoManager()
        todo = mgr.add("Task", "verify")
        result = mgr.cancel(todo.display_key)
        assert result is not None
        assert result.status == TaskStatus.CANCELLED

    def test_cancel_returns_none_for_done_todo(self):
        mgr = TodoManager()
        todo = mgr.add("Task", "verify")
        mgr.complete(todo.display_key)
        assert mgr.cancel(todo.display_key) is None

    def test_cancel_returns_none_for_nonexistent(self):
        mgr = TodoManager()
        assert mgr.cancel("nonexistent") is None


class TestTodoGetAll:
    def test_returns_copy(self):
        mgr = TodoManager()
        mgr.add("Task", "t")
        todos = mgr.get_all()
        todos.clear()
        assert len(mgr.todo_list) == 1

    def test_filter_by_status(self):
        mgr = TodoManager()
        t1 = mgr.add("Task 1", "t1")
        t2 = mgr.add("Task 2", "t2")
        mgr.complete(t1.display_key)
        pending = mgr.get_by_status(TaskStatus.PENDING)
        done = mgr.get_by_status(TaskStatus.DONE)
        assert len(pending) == 1
        assert len(done) == 1


class TestQueryStateTodoIntegration:
    def test_add_complete_via_facade(self):
        state = QueryState()
        state.add_todo("Verify", "verify")
        completed = state.complete_todo("verify")
        assert completed is not None
        assert completed.status == TaskStatus.DONE
        assert state.get_todos(status=TaskStatus.DONE)[0].semantic_key == "verify"
