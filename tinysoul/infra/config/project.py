"""Project configuration document support."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import glob

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
        if configured:
            return self.root / configured
        return self.root / default_name

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
        path = root / include
        if not path.exists():
            raise ConfigError(
                "Included configuration file does not exist",
                key="config.include",
                source=source,
                value=include,
            )
        paths = [path]
    for path in paths:
        if not path.is_file():
            raise ConfigError(
                "Configuration include must reference TOML files",
                key="config.include",
                source=source,
                value=include,
            )
    return paths


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
