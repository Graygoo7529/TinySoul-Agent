"""Unit tests for AST validation and sandboxed script execution."""

from __future__ import annotations

import ast

import pytest

from tinysoul.trap import ActionExecutionError, ActionInputError
from tinysoul.infra.sandbox import (
    _DISALLOWED_BUILTINS,
    execute_script,
    validate_ast,
)


class TestValidateAst:
    def test_accepts_safe_script(self):
        source = """
import json
import math

def _tinysoul_script(action_input, context):
    return {"sum": action_input["a"] + action_input["b"]}
"""
        tree = validate_ast(source)
        assert isinstance(tree, ast.AST)

    def test_rejects_class_definition(self):
        source = """
class Foo:
    pass

def _tinysoul_script(action_input, context):
    return 1
"""
        with pytest.raises(ActionInputError, match="Disallowed syntax: ClassDef"):
            validate_ast(source)

    def test_rejects_yield(self):
        source = """
def _tinysoul_script(action_input, context):
    yield 1
"""
        with pytest.raises(ActionInputError, match="Disallowed syntax: Yield"):
            validate_ast(source)

    @pytest.mark.parametrize("func_name", list(_DISALLOWED_BUILTINS))
    def test_rejects_disallowed_builtin_calls(self, func_name):
        source = f"""
def _tinysoul_script(action_input, context):
    {func_name}()
    return 1
"""
        with pytest.raises(
            ActionInputError, match=f"Disallowed function call: {func_name}"
        ):
            validate_ast(source)

    def test_rejects_disallowed_import(self):
        source = """
import os

def _tinysoul_script(action_input, context):
    return 1
"""
        with pytest.raises(ActionInputError, match="Disallowed import: os"):
            validate_ast(source)

    def test_allows_whitelisted_imports(self):
        source = """
import json
import math
import collections

def _tinysoul_script(action_input, context):
    return 1
"""
        validate_ast(source)  # should not raise

    def test_rejects_missing_entry_function(self):
        source = """
import json

def helper():
    return 1
"""
        with pytest.raises(ActionInputError, match=r"must define .*_tinysoul_script"):
            validate_ast(source)

    def test_rejects_syntax_error(self):
        source = "def _tinysoul_script(action_input, context)\n    return 1"
        with pytest.raises(ActionInputError, match="syntax error"):
            validate_ast(source)

    def test_rejects_import_from_disallowed_module(self):
        source = """
from os import path

def _tinysoul_script(action_input, context):
    return 1
"""
        with pytest.raises(ActionInputError, match="Disallowed import from: os"):
            validate_ast(source)


class TestExecuteScript:
    def test_executes_simple_script(self):
        source = """
def _tinysoul_script(action_input, context):
    return {"sum": action_input["a"] + action_input["b"], "ctx": context["query_events"]}
"""
        result = execute_script(
            source,
            action_input={"a": 3, "b": 4},
            context={"query_events": "hello"},
            timeout=5.0,
        )
        assert result["return_value"] == {"sum": 7, "ctx": "hello"}

    def test_allows_imported_modules(self):
        source = """
import json
import math

def _tinysoul_script(action_input, context):
    return {"pi": math.pi, "dumped": json.dumps({"x": 1})}
"""
        result = execute_script(source, {}, {}, timeout=5.0)
        assert result["return_value"]["pi"] == pytest.approx(3.14159, abs=0.001)
        assert result["return_value"]["dumped"] == '{"x": 1}'

    def test_rejects_import_outside_whitelist(self):
        source = """
import os

def _tinysoul_script(action_input, context):
    return 1
"""
        with pytest.raises(ActionInputError):
            execute_script(source, {}, {}, timeout=5.0)

    def test_rejects_open_without_workspace(self):
        source = """
def _tinysoul_script(action_input, context):
    open("/etc/passwd")
    return 1
"""
        with pytest.raises(
            ActionExecutionError, match="File access not allowed without workspace boundary"
        ):
            execute_script(source, {}, {}, timeout=5.0)

    def test_rejects_open_outside_workspace(self, tmp_path):
        source = """
def _tinysoul_script(action_input, context):
    open("/etc/passwd")
    return 1
"""
        with pytest.raises(ActionExecutionError, match="Path outside workspace"):
            execute_script(
                source, {}, {"workspace_location": str(tmp_path)}, timeout=5.0
            )

    def test_script_error_wrapped(self):
        source = """
def _tinysoul_script(action_input, context):
    raise ValueError("boom")
"""
        with pytest.raises(ActionExecutionError, match="boom"):
            execute_script(source, {}, {}, timeout=5.0)

    def test_timeout(self):
        source = """
import time

def _tinysoul_script(action_input, context):
    time.sleep(10)
    return 1
"""
        with pytest.raises(ActionExecutionError, match="timed out"):
            execute_script(source, {}, {}, timeout=0.5)

    def test_allows_open_inside_workspace(self, tmp_path):
        data_file = tmp_path / "data.txt"
        data_file.write_text("hello", encoding="utf-8")
        source = """
def _tinysoul_script(action_input, context):
    with open("data.txt", "r") as f:
        return f.read()
"""
        result = execute_script(
            source, {}, {"workspace_location": str(tmp_path)}, timeout=5.0
        )
        assert result["return_value"] == "hello"
