"""Unit tests for ActionRegistry — instance-level registration, allowlist, and caching."""

from __future__ import annotations

import json

import pytest

from tinysoul.action.framework.handler import make_handler
from tinysoul.action.framework.registry import ActionRegistry
from tinysoul.action.framework.run_config import ActionRuntimeConfig
from tinysoul.action.handlers import bootstrap
from tinysoul.infra.capabilities import ActionDependency, EnvironmentCapabilities
from tinysoul.trap import ActionExecutionError, ActionInputError
from tests.conftest import bootstrapped_registry
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider


class TestRegistryBootstrap:
    def test_calculate_is_registered(self, bootstrapped_registry):
        assert bootstrapped_registry.is_registered("calculate")

    def test_average_dog_weight_is_registered(self, bootstrapped_registry):
        assert bootstrapped_registry.is_registered("average_dog_weight")

    def test_unknown_action_is_not_registered(self, bootstrapped_registry):
        assert not bootstrapped_registry.is_registered("unknown")


class TestRegistryGetActionJson:
    def test_returns_json_string(self, bootstrapped_registry):
        action_json = bootstrapped_registry.get_action_json("calculate")
        assert '"name": "calculate"' in action_json

    def test_raises_for_unknown(self, bootstrapped_registry):
        with pytest.raises(ActionExecutionError, match="unknown"):
            bootstrapped_registry.get_action_json("unknown")


class TestRegistryGetHandler:
    def test_returns_executable_handler(self, bootstrapped_registry):
        handler = bootstrapped_registry.get_handler("calculate")
        result = handler.execute(
            {"expression": "2 + 2"},
            FakeContextProvider(),
            run_config("calculate"),
        )
        assert result["value"] == 4


class TestRegistryGetAllActionNames:
    def test_includes_builtin_actions(self, bootstrapped_registry):
        names = bootstrapped_registry.get_all_action_names()
        assert "calculate" in names
        assert "average_dog_weight" in names


class TestRegistryAllowlist:
    def test_with_allowlist_filters_available(self, bootstrapped_registry):
        filtered = bootstrapped_registry.with_allowlist(["calculate"])
        assert filtered.is_available("calculate")
        assert not filtered.is_available("average_dog_weight")

    def test_new_registration_auto_added_to_allowlist(self, bootstrapped_registry):
        filtered = bootstrapped_registry.with_allowlist(["calculate"])
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
        filtered.register("dyn", action_json, lambda: None)
        assert filtered.is_available("dyn")

    def test_with_allowlist_preserves_parent_environment_capabilities(self):
        registry = ActionRegistry(
            env_caps=EnvironmentCapabilities(executables={"sentinel-tool"})
        )
        filtered = registry.with_allowlist([])
        action_json = json.dumps({
            "name": "dyn_dep",
            "description": "Dynamic dependency test action",
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

        def factory():
            return make_handler(
                "dyn_dep",
                action_json,
                None,
                runtime_config=ActionRuntimeConfig(
                    dependencies=[
                        ActionDependency("executable", "sentinel-tool")
                    ]
                ),
            )

        filtered.register("dyn_dep", action_json, factory, strict=True)

        assert registry.is_registered("dyn_dep")
        assert filtered.is_available("dyn_dep")


class TestRegistryHandlerCache:
    def test_reuses_cached_instance(self, bootstrapped_registry):
        h1 = bootstrapped_registry.get_handler("calculate")
        h2 = bootstrapped_registry.get_handler("calculate")
        assert h1 is h2

    def test_unregister_clears_cache(self, bootstrapped_registry):
        bootstrapped_registry.get_handler("calculate")
        bootstrapped_registry.unregister("calculate")
        assert "calculate" not in bootstrapped_registry._handler_cache

    def test_isolated_instances_have_separate_caches(self, bootstrapped_registry):
        isolated = ActionRegistry()
        isolated.register(
            "calculate",
            bootstrapped_registry.get_action_json("calculate"),
            bootstrapped_registry.get_factory("calculate"),
        )
        h1 = isolated.get_handler("calculate")
        h2 = bootstrapped_registry.get_handler("calculate")
        assert h1 is not h2


class TestRegistryIsolatedInstances:
    def test_fresh_registry_is_empty(self):
        isolated = ActionRegistry()
        assert isolated.get_all_action_names() == []
        assert not isolated.is_registered("calculate")

    def test_register_unregister_round_trip(self, bootstrapped_registry):
        isolated = ActionRegistry()
        isolated.register(
            "calculate",
            bootstrapped_registry.get_action_json("calculate"),
            bootstrapped_registry.get_factory("calculate"),
        )
        assert isolated.is_registered("calculate")
        handler = isolated.get_handler("calculate")
        result = handler.execute(
            {"expression": "3 + 3"},
            FakeContextProvider(),
            run_config("calculate"),
        )
        assert result["value"] == 6
        isolated.unregister("calculate")
        assert not isolated.is_registered("calculate")

    def test_duplicate_registration_raises(self, bootstrapped_registry):
        with pytest.raises(ActionInputError, match="already registered"):
            bootstrapped_registry.register(
                "calculate",
                bootstrapped_registry.get_action_json("calculate"),
                bootstrapped_registry.get_factory("calculate"),
            )


class TestRegistryDynamicRegistration:
    def test_runtime_registration_visible_immediately(self, bootstrapped_registry):
        action_json = json.dumps(
            {
                "name": "dyn_test",
                "description": "Dynamic test action",
                "cluster": {"type": "SCRIPT", "domain": "DYNAMIC"},
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
        )

        def factory():
            from tinysoul.action.executors.script.temporary import TemporaryScriptExecutor
            return make_handler("dyn_test", action_json, TemporaryScriptExecutor("scripts/dyn.py"))

        bootstrapped_registry.register("dyn_test", action_json, factory)
        assert bootstrapped_registry.is_registered("dyn_test")
        assert "dyn_test" in bootstrapped_registry.get_available_action_names()


class TestRegistryRegistrationModes:
    """Test strict vs non-strict registration failure handling."""

    def test_factory_failure_non_strict_is_skipped(self):
        registry = ActionRegistry()

        def bad_factory():
            raise ImportError("Missing optional package")

        action_json = (
            '{"name": "skip_me", "description": "Skipped action", '
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
        registry.register("skip_me", action_json, bad_factory, strict=False)
        assert not registry.is_registered("skip_me")
        skipped = registry.get_skipped()
        assert any(name == "skip_me" for name, _ in skipped)

    def test_factory_failure_strict_raises(self):
        registry = ActionRegistry()

        def bad_factory():
            raise ImportError("Missing required package")

        action_json = (
            '{"name": "fail_me", "description": "Failing action", '
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
        with pytest.raises(ActionExecutionError, match="instantiation failed"):
            registry.register("fail_me", action_json, bad_factory, strict=True)

    def test_dependency_failure_non_strict_is_skipped(self):
        registry = ActionRegistry()
        action_json = json.dumps({
            "name": "dep_test",
            "description": "Dependency test action",
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
                "postconditions": {"logical_state_effects": [], "physical_environment_effects": []},
            },
            "detail": {
                "parameter_schema": {"type": "object"},
                "examples": [],
                "edge_case_handling": [],
            },
        })

        def factory():
            return make_handler(
                "dep_test",
                action_json,
                None,
                runtime_config=ActionRuntimeConfig(
                    dependencies=[
                        ActionDependency("executable", "this_binary_does_not_exist_12345")
                    ]
                ),
            )

        registry.register("dep_test", action_json, factory, strict=False)
        assert not registry.is_registered("dep_test")
        skipped = registry.get_skipped()
        assert any(name == "dep_test" for name, _ in skipped)

    def test_dependency_failure_strict_raises(self):
        registry = ActionRegistry()
        action_json = json.dumps({
            "name": "dep_test",
            "description": "Dependency test action",
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
                "postconditions": {"logical_state_effects": [], "physical_environment_effects": []},
            },
            "detail": {
                "parameter_schema": {"type": "object"},
                "examples": [],
                "edge_case_handling": [],
            },
        })

        def factory():
            return make_handler(
                "dep_test",
                action_json,
                None,
                runtime_config=ActionRuntimeConfig(
                    dependencies=[
                        ActionDependency("executable", "this_binary_does_not_exist_12345")
                    ]
                ),
            )

        with pytest.raises(ActionExecutionError, match="unsatisfied dependencies"):
            registry.register("dep_test", action_json, factory, strict=True)


class TestRegistryMetadataValidation:
    """Test metadata validation during registration."""

    def test_metadata_failure_non_strict_is_skipped(self):
        registry = ActionRegistry()
        # Missing required keys (cluster, profile, contract, detail)
        bad_json = '{"name": "bad_meta", "description": "Incomplete"}'

        def factory():
            from tinysoul.action.framework.handler import make_handler
            return make_handler("bad_meta", bad_json, None)

        registry.register("bad_meta", bad_json, factory, strict=False)
        assert not registry.is_registered("bad_meta")
        skipped = registry.get_skipped()
        assert any(name == "bad_meta" for name, _ in skipped)

    def test_metadata_failure_strict_raises(self):
        registry = ActionRegistry()
        bad_json = '{"name": "bad_meta", "description": "Incomplete"}'

        def factory():
            from tinysoul.action.framework.handler import make_handler
            return make_handler("bad_meta", bad_json, None)

        with pytest.raises(ActionExecutionError, match="missing required key"):
            registry.register("bad_meta", bad_json, factory, strict=True)

    def test_metadata_failure_runs_before_dependency_check(self):
        """Metadata validation should happen before dependency check."""
        registry = ActionRegistry()
        bad_json = '{"name": "bad_meta", "description": "Incomplete"}'

        def factory():
            from tinysoul.action.framework.handler import make_handler
            from tinysoul.action.framework.run_config import ActionRuntimeConfig
            from tinysoul.infra.capabilities import ActionDependency
            return make_handler(
                "bad_meta",
                bad_json,
                None,
                runtime_config=ActionRuntimeConfig(
                    dependencies=[
                        ActionDependency("executable", "this_binary_does_not_exist_12345")
                    ]
                ),
            )

        registry.register("bad_meta", bad_json, factory, strict=False)
        assert not registry.is_registered("bad_meta")
        skipped = registry.get_skipped()
        assert any(name == "bad_meta" for name, _ in skipped)
        # The skip reason should be metadata, not dependency
        assert any(
            dep.type == "metadata"
            for name, deps in skipped
            for dep in deps
            if name == "bad_meta"
        )
