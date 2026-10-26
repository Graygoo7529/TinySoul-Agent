from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tinysoul.infra.config import ConfigError, ProjectConfig


def test_project_config_loads_included_toml_files(tmp_path: Path) -> None:
    llm_dir = tmp_path / "configs" / "llm"
    model_dir = llm_dir / "models"
    model_dir.mkdir(parents=True)
    (tmp_path / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/llm/models/*.toml", "configs/llm/tasks.toml"]

        [llm.models.kimi-coding-latest]
        provider = "kimi"
        """,
        encoding="utf-8",
    )
    (model_dir / "deepseek.toml").write_text(
        """
        [llm.models.deepseek-pro]
        provider = "deepseek"
        """,
        encoding="utf-8",
    )
    (llm_dir / "tasks.toml").write_text(
        """
        [llm.tasks.framework]
        models = ["kimi-coding-latest", "deepseek-pro"]
        """,
        encoding="utf-8",
    )

    config = ProjectConfig(tmp_path)

    assert config.data["llm"]
    source = config.to_source()
    assert source.values["llm.models.kimi-coding-latest.provider"] == "kimi"
    assert source.values["llm.models.deepseek-pro.provider"] == "deepseek"
    assert source.values["llm.tasks.framework.models"] == [
        "kimi-coding-latest",
        "deepseek-pro",
    ]


def test_project_config_include_overrides_main_tree(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/runtime.toml"]

        [infra.runtime]
        max_turns = 10
        timeout = 1.0
        """,
        encoding="utf-8",
    )
    (config_dir / "runtime.toml").write_text(
        """
        [infra.runtime]
        max_turns = 20
        """,
        encoding="utf-8",
    )

    source = ProjectConfig(tmp_path).to_source()

    assert source.values["infra.runtime.max_turns"] == 20
    assert source.values["infra.runtime.timeout"] == 1.0


def test_project_config_expands_include_globs_in_stable_order(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs" / "runtime"
    config_dir.mkdir(parents=True)
    (tmp_path / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/runtime/*.toml"]
        """,
        encoding="utf-8",
    )
    (config_dir / "b.toml").write_text(
        """
        [infra.runtime]
        max_turns = 20
        timeout = 2.0
        """,
        encoding="utf-8",
    )
    (config_dir / "a.toml").write_text(
        """
        [infra.runtime]
        max_turns = 10
        """,
        encoding="utf-8",
    )

    source = ProjectConfig(tmp_path).to_source()

    assert source.values["infra.runtime.max_turns"] == 20
    assert source.values["infra.runtime.timeout"] == 2.0


def test_project_config_deduplicates_include_paths(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (tmp_path / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/runtime.toml", "configs/*.toml"]
        """,
        encoding="utf-8",
    )
    (config_dir / "runtime.toml").write_text(
        """
        [infra.runtime]
        max_turns = 20
        """,
        encoding="utf-8",
    )

    source = ProjectConfig(tmp_path).to_source()

    assert source.values["infra.runtime.max_turns"] == 20


def test_project_config_reports_unmatched_include_glob(tmp_path: Path) -> None:
    (tmp_path / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/*.toml"]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        ProjectConfig(tmp_path)


def test_project_config_rejects_include_glob_matching_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/*"]
        """,
        encoding="utf-8",
    )
    (tmp_path / "configs" / "nested").mkdir()

    with pytest.raises(ConfigError):
        ProjectConfig(tmp_path)


def test_project_config_data_deep_copies_nested_list_items(tmp_path: Path) -> None:
    (tmp_path / "tinysoul.toml").write_text(
        """
        [[infra.sources]]
        name = "a"

        [infra.sources.options]
        enabled = true
        """,
        encoding="utf-8",
    )

    config = ProjectConfig(tmp_path)

    first = config.data
    sources = first["infra"]
    assert isinstance(sources, dict)
    typed_sources = cast(dict[str, object], sources)
    source_items = typed_sources["sources"]
    assert isinstance(source_items, list)
    item = source_items[0]
    assert isinstance(item, dict)
    typed_item = cast(dict[str, object], item)
    options = typed_item["options"]
    assert isinstance(options, dict)
    typed_options = cast(dict[str, object], options)
    typed_options["enabled"] = False

    second = config.data
    second_infra = second["infra"]
    assert isinstance(second_infra, dict)
    typed_second_infra = cast(dict[str, object], second_infra)
    second_sources = typed_second_infra["sources"]
    assert isinstance(second_sources, list)
    second_item = second_sources[0]
    assert isinstance(second_item, dict)
    typed_second_item = cast(dict[str, object], second_item)
    second_options = typed_second_item["options"]
    assert isinstance(second_options, dict)
    typed_second_options = cast(dict[str, object], second_options)
    assert typed_second_options["enabled"] is True


def test_project_config_reports_missing_include(tmp_path: Path) -> None:
    (tmp_path / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/missing.toml"]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        ProjectConfig(tmp_path)


def test_project_config_uses_configured_env_file(tmp_path: Path) -> None:
    (tmp_path / "tinysoul.toml").write_text(
        """
        [config]
        env_file = "configs/.env"
        """,
        encoding="utf-8",
    )

    assert ProjectConfig(tmp_path).env_file_path() == tmp_path / "configs" / ".env"


def test_project_config_rejects_include_outside_project_root(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "outside.toml"
    outside.write_text("[outside]\nvalue = true\n", encoding="utf-8")
    (tmp_path / "tinysoul.toml").write_text(
        '[config]\ninclude = ["../outside.toml"]\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as raised:
        ProjectConfig(tmp_path)

    assert raised.value.key == "config.include"
    assert raised.value.expected == "project-relative path without '..'"


def test_project_config_rejects_env_file_outside_project_root(
    tmp_path: Path,
) -> None:
    (tmp_path / "tinysoul.toml").write_text(
        '[config]\nenv_file = "../.env"\n',
        encoding="utf-8",
    )
    config = ProjectConfig(tmp_path)

    with pytest.raises(ConfigError) as raised:
        config.env_file_path()

    assert raised.value.key == "config.env_file"
    assert raised.value.expected == "project-relative path without '..'"


def test_project_config_loads_independent_document_set_without_merging(
    tmp_path: Path,
) -> None:
    action_dir = tmp_path / "configs" / "action" / "catalog" / "core"
    action_dir.mkdir(parents=True)
    (tmp_path / "tinysoul.toml").write_text(
        """
        [config]
        include = []

        [[config.document_sets]]
        id = "action.catalog"
        include = ["configs/action/catalog/*/domain.toml"]
        """,
        encoding="utf-8",
    )
    domain_path = action_dir / "domain.toml"
    domain_path.write_text(
        'name = "core"\ndescription = "Core actions."\n',
        encoding="utf-8",
    )

    project = ProjectConfig(tmp_path)
    document_set = project.document_sets[0]

    assert document_set.set_id == "action.catalog"
    assert len(document_set.documents) == 1
    assert document_set.documents[0].source_id == (
        "project-document:action.catalog:configs/action/catalog/core/domain.toml"
    )
    assert document_set.documents[0].data["name"] == "core"
    assert "name" not in project.to_source().values


def test_project_config_rejects_document_owned_by_merged_include(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    (config_dir / "shared.toml").write_text(
        "[agent]\ninteractive = false\n", encoding="utf-8"
    )
    (tmp_path / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/shared.toml"]

        [[config.document_sets]]
        id = "test.documents"
        include = ["configs/shared.toml"]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="already owned"):
        ProjectConfig(tmp_path)
