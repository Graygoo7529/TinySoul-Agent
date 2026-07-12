"""Workspace configuration parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.config import ConfigError, reject_unknown_keys

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
DEFAULT_MAX_IMAGE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class WorkspaceSettings:
    """Workspace module settings."""

    root: Path
    manifest_path: Path = Path()
    trash_root: Path = Path()
    max_files: int = DEFAULT_MAX_FILES
    max_read_chars: int = DEFAULT_MAX_READ_CHARS
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES
    ignore_dirs: tuple[str, ...] = DEFAULT_IGNORE_DIRS

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise ConfigError(
                "Workspace root must be a path",
                key="workspace.root",
                value=self.root,
                expected="path",
            )
        if not isinstance(self.manifest_path, Path):
            raise ConfigError(
                "Workspace manifest_path must be a path",
                key="workspace.manifest_path",
                value=self.manifest_path,
                expected="path",
            )
        if not isinstance(self.trash_root, Path):
            raise ConfigError(
                "Workspace trash_root must be a path",
                key="workspace.trash_root",
                value=self.trash_root,
                expected="path",
            )
        if self.manifest_path == Path():
            object.__setattr__(
                self,
                "manifest_path",
                self.root / ".tinysoul" / "workspace_manifest.json",
            )
        if self.trash_root == Path():
            object.__setattr__(
                self,
                "trash_root",
                self.root / ".tinysoul" / "trash",
            )
        root = self.root.resolve()
        trash_root = self.trash_root.resolve()
        if root == trash_root or root not in trash_root.parents:
            raise ConfigError(
                "Workspace trash_root must be inside the active workspace root",
                key="workspace.trash_root",
                value=str(self.trash_root),
                expected="path under workspace.root",
            )
        manifest_path = self.manifest_path.resolve()
        if root == manifest_path or root not in manifest_path.parents:
            raise ConfigError(
                "Workspace manifest_path must be inside the active workspace root",
                key="workspace.manifest_path",
                value=str(self.manifest_path),
                expected="path under workspace.root",
            )
        if (
            isinstance(self.max_files, bool)
            or not isinstance(self.max_files, int)
            or self.max_files <= 0
        ):
            raise ConfigError(
                "Workspace max_files must be positive",
                key="workspace.max_files",
                value=self.max_files,
                expected="positive int",
            )
        if (
            isinstance(self.max_read_chars, bool)
            or not isinstance(self.max_read_chars, int)
            or self.max_read_chars <= 0
        ):
            raise ConfigError(
                "Workspace max_read_chars must be positive",
                key="workspace.max_read_chars",
                value=self.max_read_chars,
                expected="positive int",
            )
        if (
            isinstance(self.max_image_bytes, bool)
            or not isinstance(self.max_image_bytes, int)
            or self.max_image_bytes <= 0
        ):
            raise ConfigError(
                "Workspace max_image_bytes must be positive",
                key="workspace.max_image_bytes",
                value=self.max_image_bytes,
                expected="positive int",
            )
        if not isinstance(self.ignore_dirs, tuple):
            raise ConfigError(
                "Workspace ignore_dirs must be a tuple",
                key="workspace.ignore_dirs",
                value=self.ignore_dirs,
                expected="tuple[str, ...]",
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
    reject_unknown_keys(
        tree,
        {
            "root",
            "max_files",
            "max_read_chars",
            "max_image_bytes",
            "ignore_dirs",
        },
        key="workspace",
    )
    root = _optional_path(
        tree,
        "root",
        default=project_root / "runtime" / "workspace",
        project_root=project_root,
    )
    return WorkspaceSettings(
        root=root,
        max_files=_optional_int(tree, "max_files", default=DEFAULT_MAX_FILES),
        max_read_chars=_optional_int(
            tree,
            "max_read_chars",
            default=DEFAULT_MAX_READ_CHARS,
        ),
        max_image_bytes=_optional_int(
            tree,
            "max_image_bytes",
            default=DEFAULT_MAX_IMAGE_BYTES,
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
