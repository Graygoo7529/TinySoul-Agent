"""Workspace configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.config import ConfigError

DEFAULT_IGNORE_DIRS = (
    ".agents",
    ".codex",
    ".git",
    ".pytest-local-tmp",
    ".pytest_cache",
    ".test-tmp",
    ".tinysoul",
    "__pycache__",
)
DEFAULT_MAX_FILES = 100
DEFAULT_MAX_READ_CHARS = 4000


@dataclass(frozen=True)
class WorkspaceSettings:
    """Workspace module settings."""

    root: Path
    manifest_path: Path
    max_files: int = DEFAULT_MAX_FILES
    max_read_chars: int = DEFAULT_MAX_READ_CHARS
    ignore_dirs: tuple[str, ...] = DEFAULT_IGNORE_DIRS

    def __post_init__(self) -> None:
        if self.max_files <= 0:
            raise ConfigError(
                "Workspace max_files must be positive",
                key="workspace.max_files",
                value=self.max_files,
                expected="positive int",
            )
        if self.max_read_chars <= 0:
            raise ConfigError(
                "Workspace max_read_chars must be positive",
                key="workspace.max_read_chars",
                value=self.max_read_chars,
                expected="positive int",
            )
        for name in self.ignore_dirs:
            if not isinstance(name, str) or not name:
                raise ConfigError(
                    "Workspace ignore_dirs must contain non-empty strings",
                    key="workspace.ignore_dirs",
                    value=list(self.ignore_dirs),
                    expected="list[str]",
                )


def parse_workspace_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path,
) -> WorkspaceSettings:
    root = _optional_path(
        tree,
        "root",
        default=project_root / "runtime" / "workspace",
        project_root=project_root,
    )
    manifest_default = root / ".tinysoul" / "workspace_manifest.json"
    return WorkspaceSettings(
        root=root,
        manifest_path=_optional_path(
            tree,
            "manifest_path",
            default=manifest_default,
            project_root=project_root,
        ),
        max_files=_optional_int(tree, "max_files", default=DEFAULT_MAX_FILES),
        max_read_chars=_optional_int(
            tree,
            "max_read_chars",
            default=DEFAULT_MAX_READ_CHARS,
        ),
        ignore_dirs=_optional_str_tuple(
            tree,
            "ignore_dirs",
            default=DEFAULT_IGNORE_DIRS,
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
            "Workspace configuration value must be a non-empty path string",
            key=f"workspace.{name}",
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
            "Workspace configuration value must be an integer",
            key=f"workspace.{name}",
            value=value,
            expected="int",
        )
    return value


def _optional_str_tuple(
    tree: Mapping[str, object],
    name: str,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value = tree.get(name)
    if value is None:
        return default
    if not isinstance(value, list):
        raise ConfigError(
            "Workspace configuration value must be a list of strings",
            key=f"workspace.{name}",
            value=value,
            expected="list[str]",
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ConfigError(
                "Workspace configuration value must contain non-empty strings",
                key=f"workspace.{name}",
                value=value,
                expected="list[str]",
            )
        result.append(item)
    return tuple(result)
