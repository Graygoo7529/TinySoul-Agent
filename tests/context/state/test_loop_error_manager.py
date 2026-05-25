"""Unit tests for LoopErrorManager and feedback view generation."""

from tinysoul.context.state.loop_error import build_feedback_errors
from tinysoul.context.state import QueryState


class TestLoopErrorManager:
    def test_add_creates_item(self):
        state = QueryState()
        item = state.add_loop_error(
            turn=1, step="choose_action", error_type="LLMError", message="timeout"
        )
        assert item.turn == 1
        assert item.step == "choose_action"
        assert item.error_type == "LLMError"
        assert item.message == "timeout"
        assert len(state.loop_error_list) == 1

    def test_get_all_returns_copy(self):
        state = QueryState()
        state.add_loop_error(turn=1, step="take_action", error_type="E", message="m")
        errors = state.get_loop_error_list()
        errors.clear()
        assert len(state.loop_error_list) == 1


class TestBuildFeedbackErrors:
    def test_filters_auto_handled(self):
        state = QueryState()
        state.add_loop_error(
            turn=1, step="choose_action", error_type="E", message="auto", auto_handled=True
        )
        state.add_loop_error(
            turn=1, step="choose_action", error_type="E", message="manual", auto_handled=False
        )
        feedback = build_feedback_errors(state.get_loop_error_list())
        assert len(feedback) == 1
        assert feedback[0]["message"] == "manual"

    def test_includes_action_context_when_present(self):
        state = QueryState()
        state.add_loop_error(
            turn=2,
            step="execute_action",
            error_type="ActionExecutionError",
            message="fail",
            action_name="calculate",
            action_input={"expr": "1/0"},
        )
        feedback = build_feedback_errors(state.get_loop_error_list())
        assert feedback[0]["action_name"] == "calculate"
        assert feedback[0]["action_input"] == {"expr": "1/0"}
