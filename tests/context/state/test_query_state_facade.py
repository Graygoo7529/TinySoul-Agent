"""Unit tests for QueryState Facade — delegates correctly to managers."""

from tinysoul.context.state import QueryState


class TestQueryStateFacade:
    def test_todo_list_delegates(self):
        state = QueryState()
        state.add_todo("Task", "t")
        assert len(state.todo_list) == 1

    def test_milestone_list_delegates(self):
        state = QueryState()
        state.add_milestone("M1")
        assert state.milestone_list == ["M1"]

    def test_action_record_list_delegates(self):
        state = QueryState()
        state.record_action("a", "t", {}, {}, turn=1)
        assert len(state.action_record_list) == 1

    def test_ongoing_action_list_delegates(self):
        state = QueryState()
        state.add_ongoing_action("exec-x", "x", turn=1)
        assert state.ongoing_action_list[0]["execution_id"] == "exec-x"
        assert state.ongoing_action_list[0]["action_name"] == "x"

    def test_loop_error_list_delegates(self):
        state = QueryState()
        state.add_loop_error(turn=1, step="s", error_type="E", message="m")
        assert len(state.loop_error_list) == 1
