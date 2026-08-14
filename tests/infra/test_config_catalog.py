from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.app.initializer import ProjectConfigProfile, ProjectInitializer
from tinysoul.infra.config import ConfigEnvironment, load_config_catalog
from tinysoul.infra.config.catalog import ConfigCollectionDeletePolicy
from tinysoul.llm.adapter_types import AdapterKind
from tinysoul.llm.config_types import ProviderApiStyle
from tinysoul.llm.responses import AnswerFormat
from tinysoul.llm.tools import ToolUse


@pytest.mark.parametrize("profile", tuple(ProjectConfigProfile))
def test_config_catalog_covers_every_packaged_project_toml_leaf(
    tmp_path: Path,
    profile: ProjectConfigProfile,
) -> None:
    root = tmp_path / profile.value
    ProjectInitializer().initialize(root, config_profile=profile)
    environment = ConfigEnvironment.from_project_root(root, env={})
    catalog = load_config_catalog()

    missing = sorted(
        key
        for source in environment.sources
        if source.source_id.startswith("project:")
        for key in source.values
        if catalog.match(key) is None
    )

    assert missing == []


def test_config_catalog_static_choices_match_business_enums() -> None:
    catalog = load_config_catalog()

    assert _choices(catalog, "llm.providers.*.adapter") == {
        item.value for item in AdapterKind
    }
    assert _choices(catalog, "llm.providers.*.api_style") == {
        item.value for item in ProviderApiStyle
    }
    assert _choices(catalog, "llm.tasks.*.answer_format") == {
        item.value for item in AnswerFormat
    }
    assert _choices(catalog, "llm.tasks.*.tool_use") == {
        item.value for item in ToolUse
    }


def test_config_catalog_declares_controlled_model_creation_source() -> None:
    catalog = load_config_catalog()
    model_collection = next(
        item for item in catalog.collections if item.id == "llm.models"
    )

    assert model_collection.create_source == "project:configs/llm/models/custom.toml"
    assert (
        model_collection.delete_policy
        is ConfigCollectionDeletePolicy.CREATE_SOURCE_ONLY
    )
    assert model_collection.root == "llm.models"
    assert model_collection.identity.title == "Model ID"
    assert model_collection.to_json()["delete_policy"] == "create_source_only"


def test_config_catalog_owns_field_group_presentation() -> None:
    catalog = load_config_catalog()
    groups = {item.id: item for item in catalog.field_groups}

    assert groups
    assert all(item.group in groups for item in catalog.fields)
    assert all(groups[item.group].surface == item.surface for item in catalog.fields)
    assert catalog.to_json()["field_groups"]


def test_config_catalog_describes_action_document_fields_independently() -> None:
    catalog = load_config_catalog()
    descriptors = {
        (item.document_set, item.document_kind, item.path): item
        for item in catalog.document_fields
    }

    assert (
        "action.catalog",
        "domain",
        "description",
    ) in descriptors
    effects = descriptors[("action.catalog", "action", "semantic.effects")]
    assert {choice.value for choice in effects.choices} == {
        "read_only",
        "additive",
        "modifying",
    }
    assert catalog.to_json()["document_fields"]


def _choices(catalog, path: str) -> set[str]:
    descriptor = next(item for item in catalog.fields if item.path == path)
    return {item.value for item in descriptor.choices}
