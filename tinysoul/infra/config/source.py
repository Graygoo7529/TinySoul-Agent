"""Configuration source model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .errors import ConfigError


class ConfigSourceKind(StrEnum):
    PROJECT_TOML = "project_toml"
    DOTENV = "dotenv"
    ENVIRONMENT = "environment"
    OVERRIDE = "override"


@dataclass(frozen=True)
class ConfigSource:
    """A named configuration source with flattened dotted keys."""

    name: str
    values: Mapping[str, object]
    kind: ConfigSourceKind = ConfigSourceKind.OVERRIDE
    path: Path | None = None
    source_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ConfigError(
                "Configuration source name must be non-empty",
                key="config.source.name",
                expected="non-empty string",
            )
        if not isinstance(self.values, Mapping):
            raise ConfigError(
                "Configuration source values must be a mapping",
                key="config.source.values",
                expected="mapping[str, object]",
            )
        values = dict(self.values)
        for key in values:
            if not isinstance(key, str):
                raise ConfigError(
                    "Configuration source keys must be strings",
                    key="config.source.values",
                    value=type(key).__name__,
                    expected="string keys",
                )
        if not isinstance(self.kind, ConfigSourceKind):
            raise ConfigError(
                "Configuration source kind is invalid",
                key="config.source.kind",
                expected="ConfigSourceKind",
            )
        if self.path is not None and not isinstance(self.path, Path):
            raise ConfigError(
                "Configuration source path must be a Path",
                key="config.source.path",
                expected="Path",
            )
        if not isinstance(self.source_id, str):
            raise ConfigError(
                "Configuration source id must be a string",
                key="config.source.source_id",
                expected="string",
            )
        source_id = self.source_id or self.name
        if not source_id.strip():
            raise ConfigError(
                "Configuration source id must be non-empty",
                key="config.source.source_id",
                expected="non-empty string",
            )
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "source_id", source_id)

    @classmethod
    def empty(
        cls,
        name: str,
        *,
        kind: ConfigSourceKind = ConfigSourceKind.OVERRIDE,
        path: Path | None = None,
        source_id: str = "",
    ) -> "ConfigSource":
        return cls(
            name=name,
            values={},
            kind=kind,
            path=path,
            source_id=source_id,
        )
