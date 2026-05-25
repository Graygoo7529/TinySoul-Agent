"""Unit tests for _run_step exception routing and _apply_state_updates partial failure isolation."""

from __future__ import annotations

import pytest

from tinysoul.infra import CaptureSink, EventLogger, EventCategory, EventLevel
from tinysoul.context.state.update import apply_state_updates
from tinysoul.loop.loop import QueryLoop, _ABORT_SENTINEL, _INTERRUPT_SENTINEL
from tests.conftest import bootstrapped_registry


class TestRunStepExceptionRouting:
    def test_keyboard_interrupt_returns_sentinel(self, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test", loop_target="test", registry=bootstrapped_registry
        )

        def raise_interrupt():
            raise KeyboardInterrupt()

        result = manager._run_step("choose_action", raise_interrupt)
        assert result is _INTERRUPT_SENTINEL

    def test_continue_disposition_records_error(self, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test", loop_target="test", registry=bootstrapped_registry
        )

        def raise_error():
            raise RuntimeError("simulated")

        result = manager._run_step("choose_action", raise_error)
        assert result is None
        errors = manager.query_state.get_loop_error_list()
        assert len(errors) == 1
        assert errors[0].step == "choose_action"

    def test_abort_disposition_returns_sentinel(self, bootstrapped_registry):
        from tinysoul.trap import AbortError

        manager = QueryLoop(
            initial_query="test", loop_target="test", registry=bootstrapped_registry
        )

        def raise_abort():
            raise AbortError("fatal")

        result = manager._run_step("choose_action", raise_abort)
        assert result is _ABORT_SENTINEL
        errors = manager.query_state.get_loop_error_list()
        assert len(errors) == 1
        assert errors[0].step == "choose_action"

    def test_system_exit_propagates_immediately(self, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test", loop_target="test", registry=bootstrapped_registry
        )

        def raise_exit():
            raise SystemExit(1)

        with pytest.raises(SystemExit):
            manager._run_step("choose_action", raise_exit)


class TestApplyStateUpdatesPartialFailure:
    def test_ambiguous_todo_fails_but_others_succeed(self, bootstrapped_registry):
        sink = CaptureSink()
        logger = EventLogger(
            level=EventLevel.VERBOSE,
            categories={EventCategory.STATE},
            sinks=[sink],
        )
        manager = QueryLoop(
            initial_query="test", loop_target="test", registry=bootstrapped_registry, logger=logger
        )
        manager.query_state.add_todo("Verify A", "verify")
        manager.query_state.add_todo("Verify B", "verify")

        updates = {
            "todo_operations": [
                {"operation": "complete", "key": "verify"},
                {"operation": "add", "key": "cleanup", "description": "Clean up"},
            ],
            "milestone_operation": "add",
            "milestone_param": "Checkpoint",
        }
        apply_state_updates(manager.query_state, updates, turn=1, logger=logger)

        # ambiguous complete failed
        errors = manager.query_state.get_loop_error_list()
        assert len(errors) == 1
        assert errors[0].error_type == "TodoAmbiguityError"

        # add still succeeded
        pending = manager.query_state.get_todos()
        assert any(t.semantic_key == "cleanup" for t in pending)

        # milestone still added
        assert "Checkpoint" in manager.query_state.get_milestones()

        # verify todos remain pending
        verify_todos = [t for t in pending if t.semantic_key == "verify"]
        assert len(verify_todos) == 2

    def test_milestone_failure_does_not_discard_todos(self, bootstrapped_registry):
        manager = QueryLoop(
            initial_query="test", loop_target="test", registry=bootstrapped_registry
        )
        updates = {
            "todo_operations": [
                {"operation": "add", "key": "task", "description": "Task"}
            ],
            "milestone_operation": "add",
            "milestone_param": "",  # empty param may cause edge case
        }
        apply_state_updates(manager.query_state, updates, turn=1)
        pending = manager.query_state.get_todos()
        assert any(t.semantic_key == "task" for t in pending)


class TestNormalizeStateUpdates:
    def test_normalizes_multiple_operations(self):
        data = {
            "todo_operations": [
                {"operation": "add", "key": "verify", "description": "Verify"},
                {"operation": "complete", "key": "compute"},
            ],
            "milestone_operation": "add",
            "milestone_param": "Phase 1 done",
        }
        updates = QueryLoop._normalize_state_updates(data)
        assert len(updates["todo_operations"]) == 2
        assert updates["milestone_operation"] == "add"

    def test_raises_on_invalid_todo_operations_type(self):
        from tinysoul.trap import LLMResponseValidationError

        with pytest.raises(LLMResponseValidationError, match="must be an array"):
            QueryLoop._normalize_state_updates({"todo_operations": "bad"})

    def test_raises_on_invalid_todo_operation_element(self):
        from tinysoul.trap import LLMResponseValidationError

        with pytest.raises(LLMResponseValidationError, match="must be an object"):
            QueryLoop._normalize_state_updates({"todo_operations": ["bad"]})

    def test_raises_on_missing_required_fields(self):
        from tinysoul.trap import LLMResponseValidationError

        with pytest.raises(LLMResponseValidationError, match="missing required fields"):
            QueryLoop._normalize_state_updates(
                {"todo_operations": [{"operation": "add"}]}
            )

    def test_raises_on_invalid_operation_value(self):
        from tinysoul.trap import LLMResponseValidationError

        with pytest.raises(LLMResponseValidationError, match="Invalid todo operation"):
            QueryLoop._normalize_state_updates(
                {"todo_operations": [{"operation": "delete", "key": "x"}]}
            )

    def test_raises_on_add_missing_description(self):
        from tinysoul.trap import LLMResponseValidationError

        with pytest.raises(LLMResponseValidationError, match="requires a non-empty string 'description'"):
            QueryLoop._normalize_state_updates(
                {"todo_operations": [{"operation": "add", "key": "x"}]}
            )

    def test_raises_on_complete_missing_key(self):
        from tinysoul.trap import LLMResponseValidationError

        with pytest.raises(LLMResponseValidationError, match="requires a non-empty string 'key'"):
            QueryLoop._normalize_state_updates(
                {"todo_operations": [{"operation": "complete", "key": ""}]}
            )

    def test_raises_on_invalid_milestone_operation(self):
        from tinysoul.trap import LLMResponseValidationError

        with pytest.raises(LLMResponseValidationError, match="Invalid milestone_operation"):
            QueryLoop._normalize_state_updates(
                {"todo_operations": [], "milestone_operation": "delete"}
            )
