"""Unit tests for lightweight action validators."""

from __future__ import annotations

import json

import pytest

from tinysoul.action.framework.validation import (
    validate_action_input,
    validate_action_metadata,
)
from tinysoul.trap import ActionExecutionError, ActionInputError


# =============================================================================
# validate_action_metadata
# =============================================================================


class TestValidateActionMetadata:
    def _minimal_valid(self) -> dict:
        return {
            "name": "test_action",
            "description": "A test action",
            "cluster": {"type": "NATIVE", "domain": "TEST"},
            "profile": {
                "action_intention": "EXECUTION",
                "action_environment_effect": "READ_ONLY",
                "action_mode": "SINGLE_RUN",
                "llm_dependency": "NONE",
            },
            "contract": {
                "applicability": {"mode": "ALWAYS_CONSIDER", "conditions": []},
                "preconditions": [],
                "postconditions": {
                    "logical_state_effects": [],
                    "physical_environment_effects": [],
                },
            },
            "detail": {
                "parameter_schema": {"type": "object"},
                "examples": [],
                "edge_case_handling": [],
            },
        }

    def test_accepts_valid_metadata(self):
        raw = json.dumps(self._minimal_valid())
        result = validate_action_metadata(raw)
        assert result["name"] == "test_action"

    def test_rejects_invalid_json(self):
        with pytest.raises(ActionExecutionError, match="not valid JSON"):
            validate_action_metadata("not json")

    def test_rejects_non_object(self):
        with pytest.raises(ActionExecutionError, match="must be a JSON object"):
            validate_action_metadata("[1, 2, 3]")

    def test_rejects_missing_top_level_keys(self):
        for key in ("name", "description", "cluster", "profile", "contract", "detail"):
            data = self._minimal_valid()
            del data[key]
            with pytest.raises(ActionExecutionError, match=f"missing required key: '{key}'"):
                validate_action_metadata(json.dumps(data))

    def test_rejects_empty_description(self):
        data = self._minimal_valid()
        data["description"] = ""
        with pytest.raises(ActionExecutionError, match="'description' must be a non-empty string"):
            validate_action_metadata(json.dumps(data))

    def test_rejects_missing_cluster_keys(self):
        for key in ("type", "domain"):
            data = self._minimal_valid()
            del data["cluster"][key]
            with pytest.raises(ActionExecutionError, match=f"cluster missing required key: '{key}'"):
                validate_action_metadata(json.dumps(data))

    def test_rejects_missing_profile_keys(self):
        for key in (
            "action_intention",
            "action_environment_effect",
            "action_mode",
            "llm_dependency",
        ):
            data = self._minimal_valid()
            del data["profile"][key]
            with pytest.raises(ActionExecutionError, match=f"profile missing required key: '{key}'"):
                validate_action_metadata(json.dumps(data))

    def test_rejects_missing_contract_keys(self):
        for key in ("applicability", "preconditions", "postconditions"):
            data = self._minimal_valid()
            del data["contract"][key]
            with pytest.raises(ActionExecutionError, match=f"contract missing required key: '{key}'"):
                validate_action_metadata(json.dumps(data))

    def test_rejects_missing_applicability_mode(self):
        data = self._minimal_valid()
        del data["contract"]["applicability"]["mode"]
        with pytest.raises(ActionExecutionError, match="applicability missing required key: 'mode'"):
            validate_action_metadata(json.dumps(data))

    def test_rejects_missing_detail_parameter_schema(self):
        data = self._minimal_valid()
        del data["detail"]["parameter_schema"]
        with pytest.raises(ActionExecutionError, match="detail missing required key: 'parameter_schema'"):
            validate_action_metadata(json.dumps(data))


# =============================================================================
# validate_action_input
# =============================================================================


class TestValidateActionInput:
    def test_accepts_valid_input(self):
        schema = {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        }
        validate_action_input("calculate", schema, {"expression": "1 + 1"})

    def test_rejects_non_dict_payload(self):
        schema = {"type": "object", "required": ["x"]}
        with pytest.raises(ActionInputError, match="input must be an object"):
            validate_action_input("test", schema, "not a dict")  # type: ignore

    def test_rejects_missing_required_field(self):
        schema = {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        }
        with pytest.raises(ActionInputError, match="missing required parameter"):
            validate_action_input("calculate", schema, {})

    def test_rejects_multiple_missing_fields(self):
        schema = {"type": "object", "required": ["a", "b"]}
        with pytest.raises(ActionInputError, match="missing required parameter"):
            validate_action_input("test", schema, {"c": 1})

    def test_allows_empty_string_for_required_field(self):
        """Required field presence is checked, not emptiness."""
        schema = {"type": "object", "required": ["expression"]}
        validate_action_input("calculate", schema, {"expression": ""})

    def test_allows_optional_fields_missing(self):
        schema = {
            "type": "object",
            "properties": {"optional": {"type": "string"}},
            "required": [],
        }
        validate_action_input("test", schema, {})

    def test_allows_no_required_list(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        validate_action_input("test", schema, {})
