from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from tinysoul.infra.config import ConfigError, ConfigSource, ConfigSourceKind


def test_config_source_rejects_empty_name_as_config_error() -> None:
    with pytest.raises(ConfigError, match="Configuration source name"):
        ConfigSource("", {})


def test_config_source_rejects_invalid_metadata_types() -> None:
    with pytest.raises(ConfigError, match="source kind"):
        ConfigSource(
            "source",
            {},
            kind=cast(ConfigSourceKind, "invalid"),
        )
    with pytest.raises(ConfigError, match="source path"):
        ConfigSource(
            "source",
            {},
            path=cast(Path, "not-a-path"),
        )


def test_config_source_rejects_non_string_values_keys() -> None:
    values = cast(Mapping[str, object], {1: True})

    with pytest.raises(ConfigError, match="keys must be strings"):
        ConfigSource("source", values)


def test_config_source_defaults_id_and_owns_values_mapping() -> None:
    values = {"app.interactive": True}
    source = ConfigSource("source", values)

    values["app.interactive"] = False

    assert source.source_id == "source"
    assert source.values == {"app.interactive": True}
