from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tinysoul.infra.config import ConfigError, ProjectConfig


def test_project_config_loads_included_toml_files(local_tmp: Path) -> None:
    config_dir = local_tmp / "configs"
    config_dir.mkdir()
    (local_tmp / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/llm.models.toml", "configs/llm.tasks.toml"]

        [llm.models.kimi_k2_7]
        provider = "kimi"
        """,
        encoding="utf-8",
    )
    (config_dir / "llm.models.toml").write_text(
        """
        [llm.models.deepseek_v4]
        provider = "deepseek"
        """,
        encoding="utf-8",
    )
    (config_dir / "llm.tasks.toml").write_text(
        """
        [llm.tasks.framework]
        models = ["kimi_k2_7", "deepseek_v4"]
        """,
        encoding="utf-8",
    )

    config = ProjectConfig(local_tmp)

    assert config.data["llm"]
    source = config.to_source()
    assert source.values["llm.models.kimi_k2_7.provider"] == "kimi"
    assert source.values["llm.models.deepseek_v4.provider"] == "deepseek"
    assert source.values["llm.tasks.framework.models"] == [
        "kimi_k2_7",
        "deepseek_v4",
    ]


def test_project_config_include_overrides_main_tree(local_tmp: Path) -> None:
    config_dir = local_tmp / "configs"
    config_dir.mkdir()
    (local_tmp / "tinysoul.toml").write_text(
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

    source = ProjectConfig(local_tmp).to_source()

    assert source.values["infra.runtime.max_turns"] == 20
    assert source.values["infra.runtime.timeout"] == 1.0


def test_project_config_expands_include_globs_in_stable_order(
    local_tmp: Path,
) -> None:
    config_dir = local_tmp / "configs" / "runtime"
    config_dir.mkdir(parents=True)
    (local_tmp / "tinysoul.toml").write_text(
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

    source = ProjectConfig(local_tmp).to_source()

    assert source.values["infra.runtime.max_turns"] == 20
    assert source.values["infra.runtime.timeout"] == 2.0


def test_project_config_deduplicates_include_paths(local_tmp: Path) -> None:
    config_dir = local_tmp / "configs"
    config_dir.mkdir()
    (local_tmp / "tinysoul.toml").write_text(
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

    source = ProjectConfig(local_tmp).to_source()

    assert source.values["infra.runtime.max_turns"] == 20


def test_project_config_reports_unmatched_include_glob(local_tmp: Path) -> None:
    (local_tmp / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/*.toml"]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        ProjectConfig(local_tmp)


def test_project_config_rejects_include_glob_matching_directory(
    local_tmp: Path,
) -> None:
    (local_tmp / "configs").mkdir()
    (local_tmp / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/*"]
        """,
        encoding="utf-8",
    )
    (local_tmp / "configs" / "nested").mkdir()

    with pytest.raises(ConfigError):
        ProjectConfig(local_tmp)


def test_project_config_data_deep_copies_nested_list_items(local_tmp: Path) -> None:
    (local_tmp / "tinysoul.toml").write_text(
        """
        [[infra.sources]]
        name = "a"

        [infra.sources.options]
        enabled = true
        """,
        encoding="utf-8",
    )

    config = ProjectConfig(local_tmp)

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


def test_project_config_reports_missing_include(local_tmp: Path) -> None:
    (local_tmp / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/missing.toml"]
        """,
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        ProjectConfig(local_tmp)


def test_project_config_uses_configured_env_file(local_tmp: Path) -> None:
    (local_tmp / "tinysoul.toml").write_text(
        """
        [config]
        env_file = "configs/.env"
        """,
        encoding="utf-8",
    )

    assert ProjectConfig(local_tmp).env_file_path() == local_tmp / "configs" / ".env"
