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


@pytest.mark.packaging
def test_packaged_catalog_is_parseable_and_has_valid_domain_bindings() -> None:
    with builtin_action_catalog_root() as root:
        catalog = ActionCatalogLoader().load(root)
    assert catalog.actions()
    for action in catalog.actions():
        assert catalog.has_domain(action.domain)
        assert action.execution.executor
        assert action.tool.schema["type"] == "object"


def test_load_project_documents_preserves_sources_and_timeout_provenance(
    tmp_path: Path,
) -> None:
    _catalog_project(tmp_path)
    loaded = ActionCatalogLoader().load_documents(
        ConfigEnvironment.from_project_root(tmp_path, env={}).document_set(
            "action.catalog"
        )
    )
    assert (
        loaded.documents.domains["sample"].source_id
        == "project-document:action.catalog:catalog/sample/domain.toml"
    )
    assert loaded.documents.actions["sample.read"].path.endswith(
        "sample/actions/read.toml"
    )
    assert loaded.documents.timeout_sources["sample.read"] == "domain"
    assert loaded.catalog.get_action("sample.read").runtime.timeout_seconds == 13


def _catalog_project(root: Path, *, domain: str = "", action: str = "") -> None:
    actions = root / "catalog" / "sample" / "actions"
    actions.mkdir(parents=True)
    (root / "tinysoul.toml").write_text(
        '[[config.document_sets]]\nid="action.catalog"\n'
        'include=["catalog/*/domain.toml", "catalog/*/actions/*.toml"]\n',
        encoding="utf-8",
    )
    (actions.parent / "domain.toml").write_text(
        'name="sample"\ndescription="Sample"\n[runtime]\ntimeout_seconds=13\n' + domain,
        encoding="utf-8",
    )
    (actions / "read.toml").write_text(
        'name="sample.read"\ndomain="sample"\n[tool]\ndescription="Read"\n'
        '[tool.schema]\ntype="object"\n[execution]\nexecutor="sample.read"\n' + action,
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("domain", "action", "enabled", "source"),
    (
        ("", "", True, "default"),
        ("[visibility]\ndefault=false\n", "", False, "domain.visibility.default"),
        (
            "[visibility]\ndefault=false\n",
            "[visibility]\ndefault=true\n",
            True,
            "action.visibility.default",
        ),
    ),
)
def test_project_catalog_selection_inherits_and_tracks_provenance(
    tmp_path: Path,
    domain: str,
    action: str,
    enabled: bool,
    source: str,
) -> None:
    _catalog_project(tmp_path, domain=domain, action=action)
    catalog = ActionCatalogLoader().load(tmp_path / "catalog")
    selection = ActionPolicy.selection(
        catalog, catalog.get_action("sample.read"), "user"
    )
    assert (selection.enabled, selection.source) == (enabled, source)


def test_explicit_action_timeouts_override_domain_timeout(tmp_path: Path) -> None:
    _catalog_project(tmp_path, action="[runtime]\ntimeout_seconds=29\n")
    loaded = ActionCatalogLoader().load_documents(
        ConfigEnvironment.from_project_root(tmp_path, env={}).document_set(
            "action.catalog"
        )
    )
    assert loaded.catalog.get_action("sample.read").runtime.timeout_seconds == 29
    assert loaded.documents.timeout_sources["sample.read"] == "action"


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


def test_catalog_view_by_domain(tmp_path: Path) -> None:
    _catalog_project(tmp_path)
    catalog = ActionCatalogLoader().load(tmp_path / "catalog")
    view = catalog.with_domains(("sample",))
    assert [domain.name for domain in view.domains()] == ["sample"]
    assert view.actions() == catalog.actions_in_domain("sample")


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

[execution]
executor = "{action_name}"
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
            "execution": {"executor": "x.action"},
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
                "execution": {"executor": "x.action"},
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


def test_action_schema_enforces_object_bounds() -> None:
    schema: JsonObject = {
        "type": "object",
        "properties": {
            "where": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": 2,
            }
        },
    }
    ActionToolSpec(name="x.filter", description="Filter.", schema=schema)
    validate_action_params({"where": {"kind": "note"}}, schema=schema)
    for where in ({}, {"a": "1", "b": "2", "c": "3"}):
        with pytest.raises(ActionSchemaValidationError):
            validate_action_params(to_json_object({"where": where}), schema=schema)


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
