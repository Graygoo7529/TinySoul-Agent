from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.action import builtin_action_catalog_root
from tinysoul.action.core.loader import ActionCatalogLoader, ActionTomlParser
from tinysoul.action.core.schema import (
    ActionSchemaDefinitionError,
    ActionSchemaValidationError,
    validate_action_params,
)
from tinysoul.action.core.result import ActionTraceMode
from tinysoul.action.core.specs import ActionBackendKind, ActionParallelPolicy, ActionToolSpec
from tinysoul.infra import JsonObject
from tinysoul.infra.config import ConfigError


def test_load_builtin_catalog() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)

    assert catalog.has_domain("core")
    assert catalog.has_domain("workspace")
    assert catalog.has_domain("home")
    assert catalog.has_domain("memory")
    assert catalog.has_domain("execution")
    assert not catalog.has_domain("maintenance")
    assert not catalog.has_domain("resource")
    assert not catalog.has_domain("shell")
    assert not catalog.has_domain("script")
    assert (
        catalog.get_action("execution.run_python_script").backend.handler
        == "script.run_python"
    )
    assert (
        catalog.get_action("execution.run_python_script").backend.kind
        is ActionBackendKind.SUPERVISED_PROCESS
    )
    assert (
        catalog.get_action("execution.run_powershell").backend.kind
        is ActionBackendKind.SUPERVISED_PROCESS
    )
    answer = catalog.get_action("core.answer")
    assert answer.domain == "core"
    assert answer.tool.schema["type"] == "object"
    assert answer.runtime.timeout_seconds == 600.0
    assert answer.runtime.parallel_policy is ActionParallelPolicy.SERIAL
    assert answer.backend.handler == "core.answer"
    reason = catalog.get_action("core.reason")
    assert reason.backend.handler == "core.reason"
    create = catalog.get_action("workspace.create")
    assert create.backend.kind is ActionBackendKind.LLM_ACTION
    assert create.runtime.timeout_seconds == 600.0
    assert create.backend.options == {}
    append = catalog.get_action("workspace.append")
    assert append.backend.kind is ActionBackendKind.NATIVE
    assert append.runtime.timeout_seconds == 30.0
    rewrite = catalog.get_action("workspace.rewrite")
    assert rewrite.backend.kind is ActionBackendKind.LLM_ACTION
    assert rewrite.runtime.timeout_seconds == 600.0
    assert rewrite.backend.options == {}
    assert catalog.get_action("execution.create_script").backend.options == {
        "max_output_tokens": 16384,
        "max_output_chars": 100000,
    }
    assert catalog.get_action("execution.create_script").runtime.timeout_seconds == 600.0
    assert catalog.get_action("execution.rewrite_script").runtime.timeout_seconds == 600.0
    assert catalog.get_action("workspace.analyze").runtime.timeout_seconds == 600.0
    assert catalog.get_action("web.search_by_kimi").runtime.timeout_seconds == 600.0
    assert catalog.get_action("workspace.patch").runtime.timeout_seconds == 30.0
    assert catalog.get_action("workspace.read").runtime.timeout_seconds == 30.0
    assert (
        catalog.get_action("core.context.inspect").runtime.result.trace_mode
        is ActionTraceMode.FOLDABLE
    )
    assert (
        catalog.get_action("core.session.inspect").runtime.result.trace_mode
        is ActionTraceMode.FOLDABLE
    )
    wait_schema = catalog.get_action("execution.wait").tool.schema
    wait_properties = wait_schema["properties"]
    assert isinstance(wait_properties, dict)
    wait_seconds = wait_properties["wait_seconds"]
    assert isinstance(wait_seconds, dict)
    assert wait_seconds["minimum"] == 15
    assert wait_seconds["default"] == 15
    assert wait_seconds["maximum"] == 60
    assert catalog.get_action("execution.wait").runtime.timeout_seconds == 70.0
    assert catalog.get_action("execution.wait").backend.handler == "supervised_process.wait"


def test_llm_action_timeout_default_applies_only_without_dedicated_timeout() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader(
            llm_action_timeout_seconds=300.0,
        ).load(root)

    assert catalog.get_action("core.answer").runtime.timeout_seconds == 600.0
    assert catalog.get_action("core.reason").runtime.timeout_seconds == 600.0
    assert catalog.get_action("workspace.describe").runtime.timeout_seconds == 600.0
    assert catalog.get_action("workspace.create").runtime.timeout_seconds == 600.0
    assert catalog.get_action("workspace.analyze").runtime.timeout_seconds == 600.0
    assert catalog.get_action("workspace.read").runtime.timeout_seconds == 30.0


def test_catalog_view_by_domain() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/catalog"))

    view = catalog.with_domains(("workspace",))

    assert [domain.name for domain in view.domains()] == ["workspace"]
    assert [action.name for action in view.actions()] == [
        "workspace.analyze",
        "workspace.append",
        "workspace.convert_with_markitdown",
        "workspace.convert_with_pypdf",
        "workspace.create",
        "workspace.delete",
        "workspace.describe",
        "workspace.patch",
        "workspace.read",
        "workspace.restore",
        "workspace.rewrite",
        "workspace.scan",
        "workspace.search_text",
        "workspace.trash.list",
    ]

    execution_view = catalog.with_domains(("execution",))
    assert [action.name for action in execution_view.actions()] == [
        "execution.apply",
        "execution.create_script",
        "execution.discard",
        "execution.patch_script",
        "execution.promote_script",
        "execution.read_candidate",
        "execution.rewrite_script",
        "execution.run_bash_command",
        "execution.run_bash_script",
        "execution.run_cmd",
        "execution.run_powershell",
        "execution.run_python_script",
        "execution.stop",
        "execution.wait",
    ]

    home_view = catalog.with_domains(("home",))
    assert [action.name for action in home_view.actions()] == [
        "home.prompt_mount.patch",
        "home.prompt_mount.write",
        "home.resource.delete",
        "home.resource.patch",
        "home.resource.read",
        "home.resource.write",
        "home.top.delete",
        "home.top.patch",
        "home.top.search",
        "home.top.write",
    ]
    memory_view = catalog.with_domains(("memory",))
    assert [action.name for action in memory_view.actions()] == [
        "memory.inspect",
        "memory.memorize",
        "memory.recall",
    ]


def test_missing_catalog_root_raises_config_error() -> None:
    with pytest.raises(ConfigError) as error:
        ActionCatalogLoader().load(Path("does-not-exist"))

    assert error.value.key == "does-not-exist"


def test_action_runtime_inherits_domain_parallel_policy_when_omitted() -> None:
    parser = ActionTomlParser()
    default_runtime = parser.parse_runtime(
        {
            "timeout_seconds": 30,
            "parallel_policy": "serial",
            "hooks": {
                "normalize": ["domain_normalize"],
                "execute": ["domain_execute"],
            },
        },
        key="domain.runtime",
    )

    action = parser.parse_action(
        {
            "name": "x.action",
            "domain": "x",
            "tool": {
                "description": "Do x.",
                "schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
            "runtime": {
                "hooks": {
                    "normalize": ["action_normalize"],
                    "execute": ["action_execute"],
                }
            },
            "backend": {"kind": "native", "handler": "x.action"},
        },
        source="x/action.toml",
        default_runtime=default_runtime,
    )

    assert action.runtime.timeout_seconds == 30.0
    assert action.runtime.parallel_policy is ActionParallelPolicy.SERIAL
    assert action.runtime.hooks.normalize_hooks == (
        "domain_normalize",
        "action_normalize",
    )
    assert action.runtime.hooks.execution_hooks == (
        "domain_execute",
        "action_execute",
    )


def test_invalid_runtime_enum_raises_config_error() -> None:
    parser = ActionTomlParser()

    with pytest.raises(ConfigError) as error:
        parser.parse_runtime(
            {"parallel_policy": "sometimes"},
            key="domain.runtime",
        )

    assert error.value.key == "domain.runtime.parallel_policy"


def test_action_runtime_parses_foldable_result_trace_mode() -> None:
    runtime = ActionTomlParser().parse_runtime(
        {"result": {"trace_mode": "foldable"}},
        key="action.runtime",
    )

    assert runtime.result.trace_mode is ActionTraceMode.FOLDABLE


def test_invalid_result_trace_mode_raises_config_error() -> None:
    with pytest.raises(ConfigError) as error:
        ActionTomlParser().parse_runtime(
            {"result": {"trace_mode": "temporary"}},
            key="action.runtime",
        )

    assert error.value.key == "action.runtime.result.trace_mode"


def test_unsupported_action_schema_keyword_raises_config_error() -> None:
    parser = ActionTomlParser()

    with pytest.raises(ConfigError) as error:
        parser.parse_action(
            {
                "name": "x.action",
                "domain": "x",
                "tool": {
                    "description": "Do x.",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "pattern": "^workspace:",
                            }
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
                "backend": {"kind": "native", "handler": "x.action"},
            },
            source="x/action.toml",
        )

    assert error.value.key == "x/action.toml.tool.schema.properties.path.pattern"


def test_action_tool_spec_validates_schema_subset() -> None:
    with pytest.raises(ActionSchemaDefinitionError) as error:
        ActionToolSpec(
            name="x.action",
            description="Do x.",
            schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "pattern": "^workspace:",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )

    assert error.value.key == "ActionToolSpec(x.action).schema.properties.path.pattern"


def test_action_schema_validates_numeric_boundaries_and_default() -> None:
    schema: JsonObject = {
        "type": "object",
        "properties": {
            "wait_seconds": {
                "type": "integer",
                "minimum": 15,
                "default": 20,
                "maximum": 60,
            }
        },
        "additionalProperties": False,
    }
    ActionToolSpec(name="x.wait", description="Wait.", schema=schema)
    validate_action_params({"wait_seconds": 15}, schema=schema)
    validate_action_params({}, schema=schema)

    with pytest.raises(ActionSchemaValidationError, match=">= 15"):
        validate_action_params({"wait_seconds": 14}, schema=schema)
    with pytest.raises(ActionSchemaValidationError, match="<= 60"):
        validate_action_params({"wait_seconds": 61}, schema=schema)


def test_action_schema_rejects_inconsistent_numeric_default() -> None:
    with pytest.raises(ActionSchemaDefinitionError) as error:
        ActionToolSpec(
            name="x.wait",
            description="Wait.",
            schema={
                "type": "object",
                "properties": {
                    "wait_seconds": {
                        "type": "integer",
                        "minimum": 15,
                        "default": 10,
                        "maximum": 60,
                    }
                },
            },
        )

    assert error.value.key == (
        "ActionToolSpec(x.wait).schema.properties.wait_seconds.default"
    )
