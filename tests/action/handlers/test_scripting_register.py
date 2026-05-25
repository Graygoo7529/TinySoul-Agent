"""Tests for register_temporary_script action."""

from __future__ import annotations

import json

import pytest

from tinysoul.action.framework.manager import QueryAction
from tinysoul.action.handlers.scripting.register_temporary_script import (
    RegisterTemporaryScriptAction,
)
from tinysoul.trap import ActionExecutionError, ActionInputError
from tinysoul.llm.provider.response import AIResponse
from tests.conftest import bootstrapped_registry
from tests.helpers.factories import run_config


class MockLLMClient:
    def __init__(self, action_name="adder"):
        self._action_name = action_name
        self.calls = []

    def chat(self, messages, *, profile, system=None, config=None):
        self.calls.append(
            {
                "messages": messages,
                "profile": profile,
                "system": system,
                "config": config,
            }
        )
        payload = {
            "name": self._action_name,
            "description": f"Action {self._action_name}",
            "cluster": {"type": "SCRIPT", "domain": "MATH"},
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
                "parameter_schema": {
                    "type": "object",
                    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                },
                "examples": [],
                "edge_case_handling": [],
            },
        }
        return AIResponse(content=json.dumps(payload))


class TestRegisterTemporaryScriptAction:
    def test_successful_registration(self, tmp_path, bootstrapped_registry):
        script = tmp_path / "scripts" / "adder.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            'def _tinysoul_script(action_input, context):\n'
            '    return {"result": action_input["a"] + action_input["b"]}\n',
            encoding="utf-8",
        )

        qa = QueryAction(bootstrapped_registry.get_available_action_names(), registry=bootstrapped_registry)
        action = RegisterTemporaryScriptAction()

        class FakeWS:
            workspace_location = str(tmp_path)
            def resolve_access(self, path):
                from pathlib import Path
                return Path(self.workspace_location) / path

        class FakeCtx:
            workspace = FakeWS()
            query_events = "test"
            loop_target = "target"
            current_turn = 1
            current_state = {}
            query_action = qa
            client = MockLLMClient("adder")

            def get_loop_level_system(self):
                return [
                    {"role": "system", "content": "BASIC SYSTEM"},
                    {"role": "system", "content": "QUERY LOOP SYSTEM"},
                ]

            def append_inquiry(self, content):
                pass

            def append_response(self, content, ask_context):
                pass

            def get_current_state(self):
                return {}

            def get_workspace(self):
                return {}

            def emit_signal(self, signal):
                pass

        result = action.execute(
            {"new_action_name": "adder", "script_path": "scripts/adder.py"},
            FakeCtx(),
            run_config("register_temporary_script"),
        )
        assert "registered successfully" in result["message"]
        assert "adder" in qa.list_available_action_names()
        assert bootstrapped_registry.is_registered("adder")
        system = FakeCtx.client.calls[0]["system"]
        contents = [item["content"] for item in system]
        assert contents[0] == "BASIC SYSTEM"
        assert contents[1] == "QUERY LOOP SYSTEM"
        assert "ACTION EXECUTION CONTEXT" in contents[2]
        assert "action schema designer" in contents[3]

    def test_missing_script_file(self, tmp_path):
        action = RegisterTemporaryScriptAction()

        class FakeWS:
            workspace_location = str(tmp_path)
            def resolve_access(self, path):
                from pathlib import Path
                return Path(self.workspace_location) / path

        class FakeCtx:
            workspace = FakeWS()
            query_events = "test"
            loop_target = "target"
            current_turn = 1
            current_state = {}
            query_action = None
            client = MockLLMClient()

            def get_loop_level_system(self):
                return []

            def append_inquiry(self, content):
                pass

            def append_response(self, content, ask_context):
                pass

            def get_current_state(self):
                return {}

            def get_workspace(self):
                return {}

            def emit_signal(self, signal):
                pass

        with pytest.raises(ActionExecutionError, match="not found"):
            action.execute(
                {"new_action_name": "bad", "script_path": "scripts/missing.py"},
                FakeCtx(),
                run_config("register_temporary_script"),
            )

    def test_ast_validation_failure(self, tmp_path):
        script = tmp_path / "scripts" / "bad.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "import os\ndef _tinysoul_script(action_input, context):\n    os.system('rm -rf /')\n",
            encoding="utf-8",
        )
        action = RegisterTemporaryScriptAction()

        class FakeWS:
            workspace_location = str(tmp_path)
            def resolve_access(self, path):
                from pathlib import Path
                return Path(self.workspace_location) / path

        class FakeCtx:
            workspace = FakeWS()
            query_events = "test"
            loop_target = "target"
            current_turn = 1
            current_state = {}
            query_action = None
            client = None

            def get_loop_level_system(self):
                return []

            def append_inquiry(self, content):
                pass

            def append_response(self, content, ask_context):
                pass

            def get_current_state(self):
                return {}

            def get_workspace(self):
                return {}

            def emit_signal(self, signal):
                pass

        with pytest.raises(ActionInputError, match="Disallowed import"):
            action.execute(
                {"new_action_name": "bad", "script_path": "scripts/bad.py"},
                FakeCtx(),
                run_config("register_temporary_script"),
            )

    def test_duplicate_name_overwritten(self, tmp_path, bootstrapped_registry):
        script = tmp_path / "scripts" / "dup.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "def _tinysoul_script(action_input, context):\n    return 1\n",
            encoding="utf-8",
        )
        qa = QueryAction(bootstrapped_registry.get_available_action_names(), registry=bootstrapped_registry)
        dummy_json = (
            '{"name": "dup", "description": "Placeholder", '
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
        qa.register_action("dup", dummy_json, lambda: None)
        action = RegisterTemporaryScriptAction()

        class FakeWS:
            workspace_location = str(tmp_path)
            def resolve_access(self, path):
                from pathlib import Path
                return Path(self.workspace_location) / path

        class FakeCtx:
            workspace = FakeWS()
            query_events = "test"
            loop_target = "target"
            current_turn = 1
            current_state = {}
            query_action = qa
            client = MockLLMClient("dup")

            def get_loop_level_system(self):
                return []

            def append_inquiry(self, content):
                pass

            def append_response(self, content, ask_context):
                pass

            def get_current_state(self):
                return {}

            def get_workspace(self):
                return {}

            def emit_signal(self, signal):
                pass

        result = action.execute(
            {"new_action_name": "dup", "script_path": "scripts/dup.py"},
            FakeCtx(),
            run_config("register_temporary_script"),
        )
        assert "registered successfully" in result["message"]
        assert "dup" in qa.list_available_action_names()

    def test_generated_action_json_missing_detail_parameter_schema(self, tmp_path, bootstrapped_registry):
        """LLM returns valid JSON but missing required detail.parameter_schema."""
        script = tmp_path / "scripts" / "bad_schema.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "def _tinysoul_script(action_input, context):\n    return 1\n",
            encoding="utf-8",
        )

        qa = QueryAction(bootstrapped_registry.get_available_action_names(), registry=bootstrapped_registry)
        action = RegisterTemporaryScriptAction()

        class BadSchemaLLMClient:
            def chat(self, messages, *, profile, system=None, config=None):
                import json
                payload = {
                    "name": "bad_schema",
                    "description": "Action with missing detail",
                    "cluster": {"type": "SCRIPT", "domain": "MATH"},
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
                        # Missing parameter_schema
                        "examples": [],
                        "edge_case_handling": [],
                    },
                }
                return AIResponse(content=json.dumps(payload))

        class FakeWS:
            workspace_location = str(tmp_path)
            def resolve_access(self, path):
                from pathlib import Path
                return Path(self.workspace_location) / path

        class FakeCtx:
            workspace = FakeWS()
            query_events = "test"
            loop_target = "target"
            current_turn = 1
            current_state = {}
            query_action = qa
            client = BadSchemaLLMClient()

            def get_loop_level_system(self):
                return []

            def append_inquiry(self, content):
                pass

            def append_response(self, content, ask_context):
                pass

            def get_current_state(self):
                return {}

            def get_workspace(self):
                return {}

            def emit_signal(self, signal):
                pass

        with pytest.raises(ActionInputError, match="Required detail keys"):
            action.execute(
                {"new_action_name": "bad_schema", "script_path": "scripts/bad_schema.py"},
                FakeCtx(),
                run_config("register_temporary_script"),
            )
