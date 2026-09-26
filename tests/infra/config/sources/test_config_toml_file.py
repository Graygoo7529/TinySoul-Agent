from __future__ import annotations

from pathlib import Path

import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.sources.toml_file import ConfigFileToml


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


def test_toml_config_rejects_empty_key_as_config_error(local_tmp: Path) -> None:
    config = ConfigFileToml(local_tmp / "tinysoul.toml")

    with pytest.raises(ConfigError, match="Configuration key must be non-empty"):
        config.set_value("", 1)


def test_toml_config_rejects_nested_key_below_scalar_as_config_error(
    local_tmp: Path,
) -> None:
    config = ConfigFileToml(local_tmp / "tinysoul.toml")
    config.set_value("infra.runtime", 1)

    with pytest.raises(ConfigError, match="Cannot set nested key below scalar"):
        config.set_value("infra.runtime.max_turns", 20)


def test_toml_config_rejects_unsupported_value_as_config_error(
    local_tmp: Path,
) -> None:
    config = ConfigFileToml(local_tmp / "tinysoul.toml")
    config.set_value("infra.runtime.bad", object())

    with pytest.raises(ConfigError, match="Unsupported TOML value type"):
        config.save()


def test_retrieval_action_ids_are_atomic_map_keys_through_save_and_reload(
    local_tmp: Path,
):
    from tinysoul.infra.config import ConfigEnvironment, ProjectConfig
    from tinysoul.infra.config.descriptors import load_config_catalog
    from tinysoul.infra.config.descriptors.models import ConfigValueKind
    from tinysoul.kernel.retrieval.policy import parse_retrieval_policies

    path = local_tmp / "retrieval.toml"
    config = ConfigFileToml(path)
    mapping = {
        "home.search": {
            "sources": ["query", "refs"],
            "operations": [],
            "page": {"max_items": 7},
        },
        "core.context.search": {"sources": ["directory"], "operations": []},
    }
    config.set_value("action.retrieval", mapping)
    config.save()
    source = ConfigFileToml(path).to_source()
    assert source.values == {"action.retrieval": mapping}
    descriptor = load_config_catalog().match("action.retrieval")
    assert descriptor and descriptor.value_kind is ConfigValueKind.OBJECT
    environment = ConfigEnvironment(project=ProjectConfig(local_tmp), sources=[source])
    policies = parse_retrieval_policies(environment.section_tree("action")["retrieval"])
    assert {policy.action_id for policy in policies} == set(mapping)
    assert (
        next(
            policy for policy in policies if policy.action_id == "home.search"
        ).page_max_items
        == 7
    )
