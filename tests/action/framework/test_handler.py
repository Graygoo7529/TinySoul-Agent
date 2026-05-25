"""Unit tests for ActionHandler caching and factory functions."""

from __future__ import annotations

import json

import pytest

from tinysoul.action.framework.handler import (
    ActionHandler,
    JsonMetaProvider,
    make_handler,
    parse_meta_from_json,
    parse_detail_from_json,
)
from tinysoul.context.protocols import ContextProvider
from tinysoul.action.executors.script.temporary import TemporaryScriptExecutor


class TestParseMetaFromJson:
    def test_parses_full_schema(self):
        schema = {
            "name": "test",
            "description": "A test action",
            "cluster": {"type": "SCRIPT", "domain": "DEMO"},
            "profile": {
                "action_intention": "EXECUTION",
                "action_environment_effect": "READ_ONLY",
                "action_mode": "SINGLE_RUN",
                "llm_dependency": "NONE",
            },
            "contract": {
                "applicability": {"mode": "CONDITIONAL", "conditions": ["demo"]},
                "preconditions": [],
                "postconditions": {
                    "logical_state_effects": [],
                    "physical_environment_effects": [],
                },
            },
        }
        meta = parse_meta_from_json("test", schema)
        assert meta.name == "test"
        assert meta.cluster.type.value == "SCRIPT"
        assert meta.profile.action_intention.value == "EXECUTION"

    def test_defends_against_postconditions_as_list(self):
        """LLM may write postconditions as a list instead of a dict."""
        schema = {
            "name": "test",
            "contract": {
                "postconditions": ["effect1", "effect2"],
            },
        }
        meta = parse_meta_from_json("test", schema)
        assert meta.contract.postconditions.logical_state_effects == ["effect1", "effect2"]

    def test_defends_against_detail_fields_at_top_level(self):
        schema = {
            "name": "test",
            "parameter_schema": {"type": "object"},
            "examples": [{"x": 1}],
            "edge_case_handling": ["edge"],
        }
        detail = parse_detail_from_json(schema)
        assert detail.parameter_schema == {"type": "object"}
        assert detail.examples == [{"x": 1}]
        assert detail.edge_case_handling == ["edge"]


class TestJsonMetaProviderCache:
    def test_caches_parsed_meta(self):
        provider = JsonMetaProvider("dummy", _MINIMAL_ACTION_JSON)
        meta1 = provider.get_meta()
        meta2 = provider.get_meta()
        assert meta1 is meta2

    def test_caches_parsed_detail(self):
        provider = JsonMetaProvider("dummy", _MINIMAL_ACTION_JSON)
        detail1 = provider.get_detail()
        detail2 = provider.get_detail()
        assert detail1 is detail2


_MINIMAL_ACTION_JSON = json.dumps({
    "name": "dummy",
    "description": "d",
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
})


class TestMakeHandler:
    def test_meta_and_detail_from_json(self):
        action_json = json.dumps(
            {
                "name": "test_action",
                "description": "A test action",
                "cluster": {"type": "SCRIPT", "domain": "DEMO"},
                "profile": {
                    "action_intention": "EXECUTION",
                    "action_environment_effect": "READ_ONLY",
                    "action_mode": "SINGLE_RUN",
                    "llm_dependency": "NONE",
                },
                "contract": {
                    "applicability": {"mode": "CONDITIONAL", "conditions": ["demo"]},
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
        )
        handler = make_handler(
            "test_action",
            action_json,
            TemporaryScriptExecutor("scripts/test.py"),
        )
        meta = handler.get_meta()
        assert meta.name == "test_action"
        assert meta.description == "A test action"
        detail = handler.get_detail()
        assert detail.parameter_schema == {"type": "object"}

    def test_cache_on_handler(self):
        handler = make_handler(
            "cache_test",
            _MINIMAL_ACTION_JSON,
            None,
        )
        meta1 = handler.get_meta()
        meta2 = handler.get_meta()
        assert meta1 is meta2


class TestResolveRunConfig:
    """Verify timeout resolution hierarchy in ActionBase."""

    def test_llm_timeout_defaults_to_settings(self):
        from tinysoul.infra.config import settings
        from tinysoul.action.framework.handler import ActionBase
        from tinysoul.action.framework.run_config import RunConfig

        class DummyAction(ActionBase):
            action_name = "dummy"
            ACTION_JSON = _MINIMAL_ACTION_JSON

        action = DummyAction()
        resolved = action.resolve_run_config(RunConfig(action_name="dummy"))
        assert resolved.llm_timeout == settings.llm_timeout

    def test_llm_timeout_individual_override(self):
        from tinysoul.action.framework.handler import ActionBase
        from tinysoul.action.framework.run_config import RunConfig, ActionRuntimeConfig

        class DummyAction(ActionBase):
            action_name = "dummy"
            ACTION_JSON = _MINIMAL_ACTION_JSON
            _runtime_config = ActionRuntimeConfig(llm_timeout=99.0)

        action = DummyAction()
        resolved = action.resolve_run_config(RunConfig(action_name="dummy"))
        assert resolved.llm_timeout == 99.0

    def test_api_timeout_is_none_when_not_configured(self):
        from tinysoul.action.framework.handler import ActionBase
        from tinysoul.action.framework.run_config import RunConfig

        class DummyAction(ActionBase):
            action_name = "dummy"
            ACTION_JSON = _MINIMAL_ACTION_JSON

        action = DummyAction()
        resolved = action.resolve_run_config(RunConfig(action_name="dummy"))
        assert resolved.api_timeout is None

    def test_llm_dependency_widens_default_action_timeout(self, monkeypatch):
        from tinysoul.action.framework.handler import ActionBase
        from tinysoul.action.framework.run_config import RunConfig, ActionRuntimeConfig
        from tinysoul.infra.config import settings

        llm_action_json = json.dumps(
            {
                **json.loads(_MINIMAL_ACTION_JSON),
                "profile": {
                    "action_intention": "EXECUTION",
                    "action_environment_effect": "READ_ONLY",
                    "action_mode": "SINGLE_RUN",
                    "llm_dependency": "REQUIRED",
                },
            }
        )

        monkeypatch.setattr(settings, "action_timeout", 10.0)
        monkeypatch.setattr(settings, "llm_timeout", 40.0)
        monkeypatch.setattr(settings, "action_llm_overhead", 5.0)

        class DummyAction(ActionBase):
            action_name = "dummy"
            ACTION_JSON = llm_action_json

        action = DummyAction()
        resolved = action.resolve_run_config(RunConfig(action_name="dummy"))
        assert resolved.timeout == 45.0
        assert resolved.llm_timeout == 40.0

    def test_explicit_action_timeout_is_not_widened_by_llm_dependency(self, monkeypatch):
        from tinysoul.action.framework.handler import ActionBase
        from tinysoul.action.framework.run_config import RunConfig, ActionRuntimeConfig
        from tinysoul.infra.config import settings

        llm_action_json = json.dumps(
            {
                **json.loads(_MINIMAL_ACTION_JSON),
                "profile": {
                    "action_intention": "EXECUTION",
                    "action_environment_effect": "READ_ONLY",
                    "action_mode": "SINGLE_RUN",
                    "llm_dependency": "REQUIRED",
                },
            }
        )

        monkeypatch.setattr(settings, "llm_timeout", 40.0)
        monkeypatch.setattr(settings, "action_llm_overhead", 5.0)

        class DummyAction(ActionBase):
            action_name = "dummy"
            ACTION_JSON = llm_action_json
            _runtime_config = ActionRuntimeConfig(timeout=12.0)

        action = DummyAction()
        resolved = action.resolve_run_config(RunConfig(action_name="dummy"))
        assert resolved.timeout == 12.0

    def test_api_dependency_widens_default_action_timeout(self, monkeypatch):
        from tinysoul.action.framework.handler import ActionBase
        from tinysoul.action.framework.run_config import RunConfig, ActionRuntimeConfig
        from tinysoul.infra.config import settings

        monkeypatch.setattr(settings, "action_timeout", 10.0)
        monkeypatch.setattr(settings, "action_api_overhead", 3.0)

        class DummyAction(ActionBase):
            action_name = "dummy"
            ACTION_JSON = _MINIMAL_ACTION_JSON
            _runtime_config = ActionRuntimeConfig(
                api_timeout=22.0,
                api_dependency=True,
            )

        action = DummyAction()
        resolved = action.resolve_run_config(RunConfig(action_name="dummy"))
        assert resolved.timeout == 25.0
        assert resolved.api_timeout == 22.0
