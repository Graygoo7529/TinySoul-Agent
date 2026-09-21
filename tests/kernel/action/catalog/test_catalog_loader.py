from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.catalog import builtin_action_catalog_root
from tinysoul.kernel.action.catalog.loader import ActionCatalogLoader, ActionTomlParser
from tinysoul.kernel.action.config import ActionPolicy
from tinysoul.kernel.action.catalog.schema import (
    ActionSchemaDefinitionError,
    ActionSchemaValidationError,
    validate_action_params,
)
from tinysoul.kernel.action.result import ActionTraceMode
from tinysoul.kernel.action.catalog.specs import (
    ActionParallelPolicy,
    ActionToolSpec,
)
from tinysoul.kernel.action.errors import ActionInvariantError
from tinysoul.infra import JsonObject
from tinysoul.infra.json import to_json_object
from tinysoul.infra.config import ConfigEnvironment, ConfigError
from tests.support.project import copy_initialized_project


def test_load_builtin_catalog() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)

    for identity in (
        "execution.run_script",
        "execution.run_shell",
        "execution.start",
        "execution.stdin",
        "execution.collect",
        "home.review",
        "memory.write_daily",
    ):
        action = catalog.get_action(identity)
        assert catalog.has_domain(action.domain)
        assert action.backend.handler == identity
        assert action.tool.schema["type"] == "object"
    assert catalog.get_action("execution.run_script").tool.schema["required"] == [
        "interpreter",
        "source_link",
    ]
    assert catalog.has_action("core.job.wait")
    assert catalog.has_action("core.job.stop")


def test_load_project_documents_preserves_sources_and_timeout_provenance(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    copy_initialized_project(root)
    environment = ConfigEnvironment.from_project_root(root, env={})

    loaded = ActionCatalogLoader(
        llm_action_timeout_seconds=300.0,
    ).load_documents(environment.document_set("action.catalog"))

    assert loaded.catalog.has_action("workspace.read")
    assert loaded.documents.domains["workspace"].source_id == (
        "project-document:action.catalog:configs/action/catalog/workspace/domain.toml"
    )
    assert loaded.documents.actions["workspace.read"].path.endswith(
        "workspace/actions/read.toml"
    )
    assert loaded.documents.timeout_sources["workspace.read"] == "domain"
    assert loaded.documents.domain_runtimes["workspace"].timeout_seconds == 30.0


def test_project_catalog_enabled_policy_inherits_and_tracks_provenance(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    copy_initialized_project(root)
    domain_path = root / "configs" / "action" / "catalog" / "workspace" / "domain.toml"
    domain_path.write_text(
        domain_path.read_text(encoding="utf-8").replace(
            "default = true",
            "default = false",
        ),
        encoding="utf-8",
    )
    action_path = (
        root / "configs" / "action" / "catalog" / "workspace" / "actions" / "read.toml"
    )
    action_path.write_text(
        action_path.read_text(encoding="utf-8").replace(
            "[runtime]\nparallel_policy",
            "[visibility]\ndefault = true\n\n[runtime]\nparallel_policy",
        ),
        encoding="utf-8",
    )
    environment = ConfigEnvironment.from_project_root(root, env={})

    loaded = ActionCatalogLoader().load_documents(
        environment.document_set("action.catalog")
    )

    inherited = ActionPolicy.selection(
        loaded.catalog, loaded.catalog.get_action("workspace.append"), "user"
    )
    override = ActionPolicy.selection(
        loaded.catalog, loaded.catalog.get_action("workspace.read"), "user"
    )
    assert not inherited.enabled and inherited.source == "domain.visibility.default"
    assert override.enabled and override.source == "action.visibility.default"
    assert loaded.documents.domains["workspace"].source_id
    assert loaded.documents.actions["workspace.read"].source_id


@pytest.mark.parametrize("value", (True, False, 1, "true", None))
def test_action_runtime_rejects_retired_enabled_field(value: object) -> None:
    with pytest.raises(ConfigError) as raised:
        ActionTomlParser().parse_runtime(
            {"enabled": value},
            key="action.runtime",
        )

    assert raised.value.key == "action.runtime.enabled"


def test_llm_action_timeout_default_applies_only_without_dedicated_timeout() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader(
            llm_action_timeout_seconds=300.0,
        ).load(root)

    assert catalog.get_action("core.answer").runtime.timeout_seconds == 600.0
    assert catalog.get_action("core.reason").runtime.timeout_seconds == 600.0
    assert catalog.get_action("workspace.describe").runtime.timeout_seconds == 600.0
    assert catalog.get_action("workspace.compose").runtime.timeout_seconds == 600.0
    assert catalog.get_action("workspace.analyze").runtime.timeout_seconds == 600.0
    assert catalog.get_action("workspace.read").runtime.timeout_seconds == 30.0


@pytest.mark.parametrize("value", (0, -1, float("inf"), float("nan")))
def test_catalog_loader_rejects_invalid_llm_action_timeout(value: float) -> None:
    with pytest.raises(ConfigError) as raised:
        ActionCatalogLoader(llm_action_timeout_seconds=value)

    assert raised.value.key == "action.llm_action.timeout_seconds"
    assert raised.value.expected == "positive finite number"


@pytest.mark.parametrize("value", (0, -1, float("inf"), float("nan")))
def test_action_runtime_timeout_rejects_non_positive_or_non_finite_values(
    value: float,
) -> None:
    with pytest.raises(ConfigError) as raised:
        ActionTomlParser().parse_runtime(
            {"timeout_seconds": value},
            key="action.toml.runtime",
        )

    assert raised.value.key == "action.toml.runtime.timeout_seconds"
    assert raised.value.expected == "positive finite number | null"


def test_catalog_view_by_domain() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)

    view = catalog.with_domains(("workspace",))

    assert [domain.name for domain in view.domains()] == ["workspace"]
    assert {action.name for action in view.actions()} == {
        action.name for action in catalog.actions_in_domain("workspace")
    }

    execution_view = catalog.with_domains(("execution",))
    assert {action.name for action in execution_view.actions()} == {
        action.name for action in catalog.actions_in_domain("execution")
    }

    home_view = catalog.with_domains(("home",))
    assert {action.name for action in home_view.actions()} == {
        action.name for action in catalog.actions_in_domain("home")
    }
    core_view = catalog.with_domains(("core",))
    assert {action.name for action in core_view.actions()} == {
        action.name for action in catalog.actions_in_domain("core")
    }


def test_missing_catalog_root_raises_config_error() -> None:
    with pytest.raises(ConfigError) as error:
        ActionCatalogLoader().load(Path("does-not-exist"))

    assert error.value.key == "does-not-exist"


@pytest.mark.parametrize(
    ("action_name", "action_domain", "error_type"),
    (
        ("memory.inspect", "memory", ConfigError),
        ("memory.inspect", "core", ActionInvariantError),
    ),
)
def test_catalog_rejects_domain_identity_mismatch(
    tmp_path: Path,
    action_name: str,
    action_domain: str,
    error_type: type[Exception],
) -> None:
    root = tmp_path / "catalog"
    actions = root / "core" / "actions"
    actions.mkdir(parents=True)
    (root / "core" / "domain.toml").write_text(
        'name = "core"\ndescription = "Core."\n',
        encoding="utf-8",
    )
    (actions / "action.toml").write_text(
        f"""name = "{action_name}"
domain = "{action_domain}"

[tool]
description = "Test action."

[tool.schema]
type = "object"
required = []
additionalProperties = false

[backend]
kind = "native"
handler = "{action_name}"
""",
        encoding="utf-8",
    )

    with pytest.raises(error_type):
        ActionCatalogLoader().load(root)


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


def test_action_schema_enforces_collection_and_text_bounds() -> None:
    schema: JsonObject = {
        "type": "object",
        "properties": {
            "refs": {
                "type": "array",
                "minItems": 1,
                "maxItems": 2,
                "items": {"type": "string", "minLength": 2, "maxLength": 4},
            },
        },
    }
    ActionToolSpec(name="x.edit", description="Edit.", schema=schema)
    validate_action_params({"refs": ["ab", "abcd"]}, schema=schema)
    for refs in ([], ["ab"] * 3, ["a"], ["abcde"]):
        with pytest.raises(ActionSchemaValidationError):
            validate_action_params(to_json_object({"refs": refs}), schema=schema)


@pytest.mark.parametrize(
    "field",
    [
        {"type": "string", "maxItems": 2},
        {"type": "array", "maxItems": -1},
        {"type": "string", "minLength": True},
        {"type": "string", "minLength": 3, "maxLength": 2},
        {"type": "array", "minItems": 1, "default": []},
    ],
)
def test_action_schema_rejects_invalid_size_bounds(field: JsonObject) -> None:
    with pytest.raises(ActionSchemaDefinitionError):
        ActionToolSpec(
            name="x.edit",
            description="Edit.",
            schema={
                "type": "object",
                "properties": {"value": field},
            },
        )
