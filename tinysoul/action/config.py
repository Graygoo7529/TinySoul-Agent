"""Action module configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.config import ConfigError


@dataclass(frozen=True)
class ActionSettings:
    """Project-level Action assembly settings."""

    catalog_root: Path


def parse_action_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path,
) -> ActionSettings:
    value = tree.get("catalog_root", "tinysoul/action/catalog")
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Action catalog_root must be a non-empty path string",
            key="action.catalog_root",
            value=value,
            expected="str",
        )
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    return ActionSettings(catalog_root=path)
