"""Configuration source model."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


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
        if not self.name:
            raise ValueError("Config source name must be non-empty")
        if not isinstance(self.kind, ConfigSourceKind):
            raise ValueError("Config source kind is invalid")
        source_id = self.source_id or self.name
        if not source_id:
            raise ValueError("Config source id must be non-empty")
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
