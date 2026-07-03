from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.action.core.loader import ActionCatalogLoader, ActionTomlParser
from tinysoul.action.core.schema import ActionSchemaDefinitionError
from tinysoul.action.core.specs import ActionParallelPolicy, ActionToolSpec
from tinysoul.infra.config import ConfigError


def test_load_builtin_catalog() -> None:
    root = Path("tinysoul/action/builtin")

    catalog = ActionCatalogLoader().load(root)

    assert catalog.has_domain("core")
    assert catalog.has_domain("workspace")
    answer = catalog.get_action("core.answer")
    assert answer.domain == "core"
    assert answer.tool.schema["type"] == "object"
    assert answer.runtime.timeout_seconds == 10.0
    assert answer.runtime.parallel_policy is ActionParallelPolicy.SERIAL


def test_catalog_view_by_domain() -> None:
    catalog = ActionCatalogLoader().load(Path("tinysoul/action/builtin"))

    view = catalog.with_domains(("workspace",))

    assert [domain.name for domain in view.domains()] == ["workspace"]
    assert [action.name for action in view.actions()] == ["workspace.scan"]


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
