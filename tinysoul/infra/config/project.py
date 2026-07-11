"""Project configuration document support."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import glob

from ..filesystem import FilesystemBoundaryError, resolve_under_root
from .errors import ConfigError
from .source import ConfigSource
from .toml_file import ConfigFileToml, deep_copy_mapping, flatten_mapping, merge_trees


class ProjectConfig:
    """Merged project configuration tree from a main TOML file and includes."""

    def __init__(self, root: Path, main_file_name: str = "tinysoul.toml") -> None:
        self.root = root
        self.main_path = root / main_file_name
        self._data = self._load()

    @property
    def data(self) -> dict[str, object]:
        return deep_copy_mapping(self._data)

    def to_source(self) -> ConfigSource:
        return ConfigSource(name=str(self.main_path), values=flatten_mapping(self._data))

    def env_file_path(self, default_name: str = ".env") -> Path:
        configured = _get_config_string(self._data, "env_file")
        value = configured or default_name
        return _project_path(
            self.root,
            value,
            key="config.env_file",
            source=str(self.main_path),
        )

    def _load(self) -> dict[str, object]:
        main = ConfigFileToml(self.main_path).data
        result = deep_copy_mapping(main)
        for include_path in _expand_include_paths(
            self.root,
            _get_config_string_list(main, "include"),
            source=str(self.main_path),
        ):
            include_data = ConfigFileToml(include_path).data
            if _get_config_string_list(include_data, "include"):
                raise ConfigError(
                    "Nested configuration includes are not supported",
                    key="config.include",
                    source=str(include_path),
                    value=str(include_path),
                )
            result = merge_trees(result, include_data)
        return result


def _expand_include_paths(root: Path, includes: list[str], *, source: str) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for include in includes:
        matches = _include_matches(root, include, source=source)
        for path in matches:
            normalized = path.resolve()
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(path)
    return result


def _include_matches(root: Path, include: str, *, source: str) -> list[Path]:
    _validate_relative_project_path(
        include,
        key="config.include",
        source=source,
    )
    if _has_glob_pattern(include):
        matches = sorted(root.glob(include), key=lambda path: path.as_posix())
        if not matches:
            raise ConfigError(
                "Configuration include pattern did not match any files",
                key="config.include",
                source=source,
                value=include,
            )
        paths = matches
    else:
        path = _project_path(
            root,
            include,
            key="config.include",
            source=source,
        )
        if not path.exists():
            raise ConfigError(
                "Included configuration file does not exist",
                key="config.include",
                source=source,
                value=include,
            )
        paths = [path]
    for path in paths:
        _ensure_under_project_root(
            root,
            path,
            value=include,
            key="config.include",
            source=source,
        )
        if not path.is_file():
            raise ConfigError(
                "Configuration include must reference TOML files",
                key="config.include",
                source=source,
                value=include,
            )
    return paths


def _project_path(
    root: Path,
    value: str,
    *,
    key: str,
    source: str,
) -> Path:
    _validate_relative_project_path(value, key=key, source=source)
    candidate = root / value
    try:
        resolve_under_root(root, value)
    except FilesystemBoundaryError as exc:
        raise ConfigError(
            "Project configuration path must stay within the project root",
            key=key,
            source=source,
            value=value,
            expected="project-relative path",
        ) from exc
    return candidate


def _validate_relative_project_path(value: str, *, key: str, source: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ConfigError(
            "Project configuration path must stay within the project root",
            key=key,
            source=source,
            value=value,
            expected="project-relative path without '..'",
        )


def _ensure_under_project_root(
    root: Path,
    path: Path,
    *,
    value: str,
    key: str,
    source: str,
) -> None:
    try:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
            raise FilesystemBoundaryError(
                f"Path escapes root: {value}",
                root=resolved_root,
                path=resolved_path,
            )
    except FilesystemBoundaryError as exc:
        raise ConfigError(
            "Project configuration path must stay within the project root",
            key=key,
            source=source,
            value=value,
            expected="project-relative path",
        ) from exc


def _has_glob_pattern(value: str) -> bool:
    return glob.has_magic(value)


def _get_config_string(data: Mapping[str, object], key: str) -> str | None:
    config = data.get("config")
    if not isinstance(config, Mapping):
        return None
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(
            "Project configuration value must be a string",
            key=f"config.{key}",
            value=value,
            expected="str",
        )
    return value


def _get_config_string_list(data: Mapping[str, object], key: str) -> list[str]:
    config = data.get("config")
    if not isinstance(config, Mapping):
        return []
    value = config.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(
            "Project configuration value must be a list of strings",
            key=f"config.{key}",
            value=value,
            expected="list[str]",
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(
                "Project configuration value must be a list of strings",
                key=f"config.{key}",
                value=value,
                expected="list[str]",
            )
        result.append(item)
    return result
