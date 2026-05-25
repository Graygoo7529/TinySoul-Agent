"""Unit tests for Calculate action."""

from tinysoul.action.handlers.math.calculate import CalculateAction
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider


class TestCalculateAction:
    def test_addition(self):
        action = CalculateAction()
        result = action.execute(
            {"expression": "10 + 20"},
            FakeContextProvider(),
            run_config("calculate"),
        )
        assert result["value"] == 30

    def test_floating_point(self):
        action = CalculateAction()
        result = action.execute(
            {"expression": "4 * 7 / 3"},
            FakeContextProvider(),
            run_config("calculate"),
        )
        assert abs(result["value"] - 9.333333333333334) < 0.0001

    def test_empty_expression_raises(self):
        from tinysoul.trap import ActionInputError
        import pytest

        action = CalculateAction()
        with pytest.raises(ActionInputError, match="No expression"):
            action.execute(
                {"expression": ""},
                FakeContextProvider(),
                run_config("calculate"),
            )

    def test_missing_expression_raises(self):
        from tinysoul.trap import ActionInputError
        import pytest

        action = CalculateAction()
        with pytest.raises(ActionInputError, match="No expression"):
            action.execute({}, FakeContextProvider(), run_config("calculate"))
