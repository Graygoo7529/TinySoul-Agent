from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.infra.config import ConfigError, ProjectConfig


def test_project_config_loads_included_toml_files(local_tmp: Path) -> None:
    config_dir = local_tmp / "configs"
    config_dir.mkdir()
    (local_tmp / "tinysoul.toml").write_text(
        """
        [config]
        include = ["configs/llm.models.toml", "configs/llm.chains.toml"]

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
    (config_dir / "llm.chains.toml").write_text(
        """
        [llm.chains.framework_default]
        models = ["kimi_k2_7", "deepseek_v4"]
        """,
        encoding="utf-8",
    )

    config = ProjectConfig(local_tmp)

    assert config.data["llm"]
    source = config.to_source()
    assert source.values["llm.models.kimi_k2_7.provider"] == "kimi"
    assert source.values["llm.models.deepseek_v4.provider"] == "deepseek"
    assert source.values["llm.chains.framework_default.models"] == [
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

