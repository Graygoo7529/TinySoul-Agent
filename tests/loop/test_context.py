"""Unit tests for QueryContext — state serialization and todo key exposure rules."""

from __future__ import annotations

from unittest.mock import MagicMock

from tinysoul.action.framework.manager import QueryAction
from tinysoul.loop.context import QueryContext
from tinysoul.context.state import QueryState
from tests.helpers.factories import QueryStateBuilder


def _mock_query_action() -> QueryAction:
    """Return a QueryAction with a mock registry (no real actions needed)."""
    mock_registry = MagicMock()
    mock_registry.with_allowlist.return_value = MagicMock()
    return QueryAction([], registry=mock_registry)


class TestQueryContextCurrentStateOrder:
    def test_field_order_has_records_and_errors_at_top(self):
        state = QueryStateBuilder().with_action_record("calc", turn=1).build()
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=state,
            query_action=_mock_query_action(),
        )
        result = ctx.get_current_state()
        keys = list(result.keys())
        assert keys[0] == "action_record_list"
        assert keys[1] == "feedback_error_list"
        assert keys[2] == "todo_list"

    def test_action_records_are_structured_dicts_without_timestamp(self):
        state = QueryStateBuilder().with_action_record(
            "calculate", action_target="Compute", action_input={"expr": "1+1"}, action_result={"value": "2", "expression": "1+1"}, turn=1
        ).build()
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=state,
            query_action=_mock_query_action(),
        )
        records = ctx.get_current_state()["action_record_list"]
        assert len(records) == 1
        assert records[0]["turn"] == 1
        assert records[0]["action_name"] == "calculate"
        assert "timestamp" not in records[0]


class TestQueryContextTodoKeyExposure:
    def test_exposes_semantic_key_when_unique(self):
        state = QueryStateBuilder().with_todo("Task A", "verify").build()
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=state,
            query_action=_mock_query_action(),
        )
        todos = ctx.get_current_state()["todo_list"]
        assert len(todos) == 1
        assert todos[0]["key"] == "verify"

    def test_exposes_display_key_when_semantic_key_reused(self):
        state = (
            QueryStateBuilder()
            .with_todo("Task A", "verify")
            .with_todo("Task B", "verify")
            .build()
        )
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=state,
            query_action=_mock_query_action(),
        )
        todos = ctx.get_current_state()["todo_list"]
        assert len(todos) == 2
        assert todos[0]["key"] == "verify-1"
        assert todos[1]["key"] == "verify-2"

    def test_completed_todo_participates_in_conflict_detection(self):
        state = (
            QueryStateBuilder()
            .with_completed_todo("Old", "verify")
            .with_todo("New", "verify")
            .build()
        )
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=state,
            query_action=_mock_query_action(),
        )
        todos = ctx.get_current_state()["todo_list"]
        assert todos[0]["key"] == "verify-1"
        assert todos[1]["key"] == "verify-2"

    def test_cancelled_todo_participates_in_conflict_detection(self):
        state = (
            QueryStateBuilder()
            .with_cancelled_todo("Old", "verify")
            .with_todo("New", "verify")
            .build()
        )
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=state,
            query_action=_mock_query_action(),
        )
        todos = ctx.get_current_state()["todo_list"]
        assert todos[0]["key"] == "verify-1"
        assert todos[1]["key"] == "verify-2"


class TestQueryContextPeekAndAckActionRecords:
    def test_peek_returns_unread_without_marking(self):
        state = QueryStateBuilder().with_action_record("calc", turn=1).build()
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=state,
            query_action=_mock_query_action(),
        )
        new_records = ctx.peek_new_action_records()
        assert len(new_records) == 1
        assert new_records[0]["action_name"] == "calc"
        assert all(not r.read for r in state.get_action_record_list())

    def test_ack_marks_records_as_read(self):
        state = QueryStateBuilder().with_action_record("calc", turn=1).build()
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=state,
            query_action=_mock_query_action(),
        )
        ctx.peek_new_action_records()
        ctx.ack_action_records()
        assert all(r.read for r in state.get_action_record_list())
        assert ctx.peek_new_action_records() == []

    def test_returns_empty_when_all_read(self):
        state = QueryStateBuilder().with_action_record("calc", turn=1).build()
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=state,
            query_action=_mock_query_action(),
        )
        ctx.ack_action_records()
        second = ctx.peek_new_action_records()
        assert second == []


class TestQueryContextWorkspaceData:
    def test_returns_workspace_dict_when_present(self):
        from tinysoul.context.workspace import ResourceItem, ResourceType, Workspace

        ws = Workspace(workspace_location="/tmp/test")
        ws.add_resource(
            ResourceItem(
                resource_name="a.md",
                resource_type=ResourceType.MARKDOWN,
                resource_access="a.md",
            )
        )
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=QueryState(),
            query_action=_mock_query_action(),
            workspace=ws,
        )
        data = ctx.get_workspace()
        assert len(data["resources"]) == 1

    def test_returns_empty_dict_when_no_workspace(self):
        ctx = QueryContext(
            query_events="test",
            loop_target="test",
            query_state=QueryState(),
            query_action=_mock_query_action(),
        )
        assert ctx.get_workspace() == {}
