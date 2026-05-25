"""Unit tests for QueryAction — action execution, metadata, and dynamic registration."""

from __future__ import annotations

import pytest

from tinysoul.action.framework.manager import QueryAction
from tinysoul.trap import (
    ActionInputError,
    ActionNotFoundError,
)
from tests.conftest import bootstrapped_registry
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider


class TestQueryActionInit:
    def test_filters_by_allowlist(self, bootstrapped_registry):
        qa = QueryAction(
            available_actions=["calculate", "average_dog_weight"],
            registry=bootstrapped_registry,
        )
        assert qa.list_available_action_names() == ["average_dog_weight", "calculate"]
        assert qa.is_action_available("calculate")
        assert not qa.is_action_available("delete_file")

    def test_empty_allowlist_is_empty(self, bootstrapped_registry):
        qa = QueryAction(available_actions=[], registry=bootstrapped_registry)
        assert qa.list_available_action_names() == []


class TestQueryActionExecute:
    def test_execute_calculate(self, bootstrapped_registry):
        qa = QueryAction(["calculate"], registry=bootstrapped_registry)
        result = qa.execute(
            "calculate",
            {"expression": "4 * 7 / 3"},
            context_provider=FakeContextProvider(),
            run_config=run_config("calculate"),
        )
        assert "value" in result
        assert abs(result["value"] - 9.333333333333334) < 0.0001
        assert result["expression"] == "4 * 7 / 3"

    def test_execute_calculate_addition(self, bootstrapped_registry):
        qa = QueryAction(["calculate"], registry=bootstrapped_registry)
        result = qa.execute(
            "calculate",
            {"expression": "10 + 20"},
            context_provider=FakeContextProvider(),
            run_config=run_config("calculate"),
        )
        assert result["value"] == 30

    def test_execute_average_dog_weight_known(self, bootstrapped_registry):
        qa = QueryAction(["average_dog_weight"], registry=bootstrapped_registry)
        result = qa.execute(
            "average_dog_weight",
            {"breed": "Border Collie"},
            context_provider=FakeContextProvider(),
            run_config=run_config("average_dog_weight"),
        )
        assert "37 lbs" in result["average_weight"]

    def test_execute_average_dog_weight_unknown(self, bootstrapped_registry):
        qa = QueryAction(["average_dog_weight"], registry=bootstrapped_registry)
        result = qa.execute(
            "average_dog_weight",
            {"breed": "Unknown"},
            context_provider=FakeContextProvider(),
            run_config=run_config("average_dog_weight"),
        )
        assert "50 lbs" in result["average_weight"]

    def test_execute_unregistered_raises(self, bootstrapped_registry):
        qa = QueryAction(["calculate"], registry=bootstrapped_registry)
        with pytest.raises(ActionNotFoundError, match="unregistered"):
            qa.execute(
                "unregistered",
                {},
                context_provider=FakeContextProvider(),
                run_config=run_config("unregistered"),
            )

    def test_execute_calculate_empty_expression_raises(self, bootstrapped_registry):
        qa = QueryAction(["calculate"], registry=bootstrapped_registry)
        with pytest.raises(ActionInputError, match="No expression"):
            qa.execute(
                "calculate",
                {"expression": ""},
                context_provider=FakeContextProvider(),
                run_config=run_config("calculate"),
            )

    def test_execute_missing_required_field_raises(self, bootstrapped_registry):
        qa = QueryAction(["calculate"], registry=bootstrapped_registry)
        with pytest.raises(ActionInputError, match="missing required parameter"):
            qa.execute(
                "calculate",
                {},
                context_provider=FakeContextProvider(),
                run_config=run_config("calculate"),
            )


class TestQueryActionGetMeta:
    def test_returns_list_of_meta_dicts(self, bootstrapped_registry):
        qa = QueryAction(["calculate"], registry=bootstrapped_registry)
        meta_list = qa.get_available_actions_meta()
        assert len(meta_list) == 1
        assert meta_list[0]["name"] == "calculate"
        assert "cluster" in meta_list[0]
        assert "profile" in meta_list[0]
        assert "contract" in meta_list[0]

    def test_profile_values_are_text(self, bootstrapped_registry):
        qa = QueryAction(["calculate"], registry=bootstrapped_registry)
        meta = qa.get_available_actions_meta()[0]
        profile = meta["profile"]
        assert profile["action_intention"] == "EXECUTION"
        assert profile["action_environment_effect"] == "READ_ONLY"
        assert profile["action_mode"] == "SINGLE_RUN"
        assert profile["llm_dependency"] == "NONE"

    def test_empty_actions_returns_empty(self, bootstrapped_registry):
        qa = QueryAction([], registry=bootstrapped_registry)
        assert qa.get_available_actions_meta() == []


class TestQueryActionGetDetail:
    def test_returns_parameter_schema(self, bootstrapped_registry):
        qa = QueryAction(["calculate"], registry=bootstrapped_registry)
        detail = qa.get_selected_action_detail("calculate")
        assert "parameter_schema" in detail
        assert "examples" in detail
        assert "edge_case_handling" in detail

    def test_unavailable_action_raises(self, bootstrapped_registry):
        qa = QueryAction(["calculate"], registry=bootstrapped_registry)
        with pytest.raises(ActionNotFoundError, match="unknown"):
            qa.get_selected_action_detail("unknown")


class TestQueryActionDynamicRegistration:
    def test_register_action_immediately_visible(self, bootstrapped_registry):
        qa = QueryAction([], registry=bootstrapped_registry)
        action_json = (
            '{"name": "dyn", "description": "Dynamic test action", '
            '"cluster": {"type": "NATIVE", "domain": "TEST"}, '
            '"profile": {"action_intention": "EXECUTION", '
            '"action_environment_effect": "READ_ONLY", '
            '"action_mode": "SINGLE_RUN", "llm_dependency": "NONE"}, '
            '"contract": {"applicability": {"mode": "ALWAYS_CONSIDER", "conditions": []}, '
            '"preconditions": [], '
            '"postconditions": {"logical_state_effects": [], "physical_environment_effects": []}}, '
            '"detail": {"parameter_schema": {"type": "object"}, '
            '"examples": [], "edge_case_handling": []}}'
        )
        qa.register_action(
            "dyn",
            action_json,
            lambda: None,  # type: ignore[arg-type, return-value]
        )
        assert "dyn" in qa.list_available_action_names()
