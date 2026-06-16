from __future__ import annotations

from pathlib import Path

from tinysoul.infra.config.toml_file import ConfigFileToml


def test_toml_config_reads_toml_as_dotted_source(local_tmp: Path) -> None:
    path = local_tmp / "tinysoul.toml"
    path.write_text(
        """
        [infra.runtime]
        max_turns = 20
        parallel_workers = 5
        """,
        encoding="utf-8",
    )

    source = ConfigFileToml(path).to_source()

    assert source.values["infra.runtime.max_turns"] == 20
    assert source.values["infra.runtime.parallel_workers"] == 5


def test_toml_config_set_value_and_save_round_trips(local_tmp: Path) -> None:
    path = local_tmp / "tinysoul.toml"
    config = ConfigFileToml(path)

    config.set_value("infra.runtime.max_turns", 40)
    config.set_value("infra.logging.level", "debug")
    config.set_value("infra.logging.color", True)
    config.set_value("infra.runtime.tags", ["a", "b"])
    config.save()

    reloaded = ConfigFileToml(path).to_source()

    assert reloaded.values["infra.runtime.max_turns"] == 40
    assert reloaded.values["infra.logging.level"] == "debug"
    assert reloaded.values["infra.logging.color"] is True
    assert reloaded.values["infra.runtime.tags"] == ["a", "b"]


def test_toml_config_data_returns_copy(local_tmp: Path) -> None:
    path = local_tmp / "tinysoul.toml"
    path.write_text("[infra.runtime]\nmax_turns = 20\n", encoding="utf-8")
    config = ConfigFileToml(path)

    data = config.data
    data["infra"] = {}

    assert config.to_source().values["infra.runtime.max_turns"] == 20

