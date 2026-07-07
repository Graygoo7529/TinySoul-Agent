"""Agent Home configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.config import ConfigError

DEFAULT_MAX_READ_CHARS = 4000


@dataclass(frozen=True)
class AgentHomeSettings:
    """Agent Home module settings."""

    original_root: Path
    runtime_root: Path
    max_read_chars: int = DEFAULT_MAX_READ_CHARS

    def __post_init__(self) -> None:
        if self.max_read_chars <= 0:
            raise ConfigError(
                "Agent Home max_read_chars must be positive",
                key="home.max_read_chars",
                value=self.max_read_chars,
                expected="positive int",
            )


def parse_agent_home_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path,
) -> AgentHomeSettings:
    original_root = _optional_path(
        tree,
        "root",
        default=project_root,
        project_root=project_root,
    )
    return AgentHomeSettings(
        original_root=original_root,
        runtime_root=_optional_path(
            tree,
            "runtime_root",
            default=project_root / "runtime" / "home",
            project_root=project_root,
        ),
        max_read_chars=_optional_int(
            tree,
            "max_read_chars",
            default=DEFAULT_MAX_READ_CHARS,
        ),
    )


def _optional_path(
    tree: Mapping[str, object],
    name: str,
    *,
    default: Path,
    project_root: Path,
) -> Path:
    value = tree.get(name)
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ConfigError(
            "Agent Home configuration value must be a non-empty path string",
            key=f"home.{name}",
            value=value,
            expected="str",
        )
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root / path


def _optional_int(
    tree: Mapping[str, object],
    name: str,
    *,
    default: int,
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Agent Home configuration value must be an integer",
            key=f"home.{name}",
            value=value,
            expected="int",
        )
    return value
