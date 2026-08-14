from __future__ import annotations

from dataclasses import replace

import pytest

from tinysoul.action import ActionToolSpec, builtin_action_catalog_root
from tinysoul.action.core.loader import ActionCatalogLoader
from tinysoul.app import ProjectInitializer
from tinysoul.capabilities.supervised_process import (
    compile_supervised_process_wait_policy,
    parse_supervised_process_wait_policy,
)
from tinysoul.infra.config import ConfigEnvironment, ConfigError


def test_wait_policy_compiles_from_action_schema() -> None:
    with builtin_action_catalog_root() as root:
        loaded = ActionCatalogLoader().load(root)
        action = loaded.get_action("execution.wait")

    policy = parse_supervised_process_wait_policy(action)

    assert policy.minimum_seconds == 15
    assert policy.default_seconds == 15
    assert policy.maximum_seconds == 60


def test_wait_policy_requires_action_owned_boundaries() -> None:
    with builtin_action_catalog_root() as root:
        action = ActionCatalogLoader().load(root).get_action("execution.wait")
    raw_properties = action.tool.schema["properties"]
    assert isinstance(raw_properties, dict)
    properties = dict(raw_properties)
    raw_wait_schema = properties["wait_seconds"]
    assert isinstance(raw_wait_schema, dict)
    wait_schema = dict(raw_wait_schema)
    del wait_schema["default"]
    properties["wait_seconds"] = wait_schema
    schema = dict(action.tool.schema)
    schema["properties"] = properties
    action = replace(
        action,
        tool=ActionToolSpec(
            name=action.name,
            description=action.tool.description,
            schema=schema,
        ),
    )

    with pytest.raises(ConfigError) as raised:
        parse_supervised_process_wait_policy(action, source="wait.toml")

    assert raised.value.key == "tool.schema.properties.wait_seconds.default"
    assert raised.value.source == "wait.toml"


def test_loaded_catalog_compiler_preserves_document_source(tmp_path) -> None:
    root = tmp_path / "project"
    ProjectInitializer().initialize(root)
    wait_path = (
        root
        / "configs"
        / "action"
        / "catalog"
        / "execution"
        / "actions"
        / "wait.toml"
    )
    wait_path.write_text(
        wait_path.read_text(encoding="utf-8").replace("default = 15\n", ""),
        encoding="utf-8",
    )
    environment = ConfigEnvironment.from_project_root(root, env={})
    loaded = ActionCatalogLoader().load_documents(
        environment.document_set("action.catalog")
    )

    with pytest.raises(ConfigError) as raised:
        compile_supervised_process_wait_policy(loaded)

    assert raised.value.source.startswith("project-document:action.catalog:")
