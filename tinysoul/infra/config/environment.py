"""Unified configuration environment."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import fields, is_dataclass, replace
from enum import Enum
import os
from pathlib import Path
from types import NoneType
from typing import TypeVar, cast, get_args, get_origin, get_type_hints

from .dotenv import DotenvSource, _env_mapping_to_dotted
from .errors import ConfigError
from .project import ProjectConfig
from .source import ConfigSource, ConfigSourceKind
from .toml_file import deep_copy_mapping

T = TypeVar("T")


class ConfigEnvironment:
    """Project configuration tree plus ordered runtime configuration sources."""

    def __init__(
        self,
        *,
        project: ProjectConfig,
        sources: list[ConfigSource],
        runtime_env: Mapping[str, str] | None = None,
        process_env: Mapping[str, str] | None = None,
        project_tree: Mapping[str, object] | None = None,
        dotenv_path: Path | None = None,
    ) -> None:
        self._project = project
        self._sources = list(sources)
        self._runtime_env = dict(runtime_env or {})
        self._process_env = dict(process_env or {})
        self._project_tree = deep_copy_mapping(
            project_tree if project_tree is not None else project.data
        )
        self._dotenv_path = dotenv_path or project.env_file_path()

    @classmethod
    def from_project_root(
        cls,
        root: Path,
        *,
        project_file_name: str = "tinysoul.toml",
        dotenv_name: str = ".env",
        env: Mapping[str, str] | None = None,
        overrides: Mapping[str, object] | None = None,
    ) -> "ConfigEnvironment":
        project = ProjectConfig(root=root, main_file_name=project_file_name)
        dotenv = DotenvSource(project.env_file_path(default_name=dotenv_name))
        dotenv_raw = dotenv.load_raw()
        process_env = dict(env if env is not None else os.environ)
        sources = [
            *project.sources,
            dotenv.load(),
            ConfigSource(
                name="environment",
                values=_env_mapping_to_dotted(process_env),
                kind=ConfigSourceKind.ENVIRONMENT,
                source_id="environment",
            ),
        ]
        if overrides:
            sources.append(
                ConfigSource(
                    name="overrides",
                    values=dict(overrides),
                    kind=ConfigSourceKind.OVERRIDE,
                    source_id="overrides",
                )
            )
        return cls(
            project=project,
            sources=sources,
            runtime_env={**dotenv_raw, **process_env},
            process_env=process_env,
        )

    @property
    def project_tree(self) -> dict[str, object]:
        return deep_copy_mapping(self._project_tree)

    @property
    def project(self) -> ProjectConfig:
        """Project source graph and its configured dotenv path."""

        return self._project

    @property
    def sources(self) -> tuple[ConfigSource, ...]:
        return tuple(self._sources)

    @property
    def runtime_env(self) -> dict[str, str]:
        return dict(self._runtime_env)

    @property
    def process_env(self) -> dict[str, str]:
        return dict(self._process_env)

    @property
    def dotenv_path(self) -> Path:
        return self._dotenv_path

    def effective_values(self) -> dict[str, object]:
        """Return the flattened values after source precedence is applied."""

        values: dict[str, object] = {}
        for source in self._sources:
            values.update(source.values)
        return values

    def source_id_for(self, key: str) -> str:
        """Return the winning source identity for a dotted key."""

        if not key:
            return ""
        prefix = f"{key}."
        for source in reversed(self._sources):
            if key in source.values or any(
                candidate.startswith(prefix) for candidate in source.values
            ):
                return source.source_id
        parts = key.split(".")
        for end in range(len(parts) - 1, 0, -1):
            parent = ".".join(parts[:end])
            for source in reversed(self._sources):
                if parent in source.values:
                    return source.source_id
        return ""

    def source_for(self, key: str) -> str:
        """Return the winning or nearest owning source for a dotted key."""

        if not key:
            return ""
        prefix = f"{key}."
        for source in reversed(self._sources):
            if key in source.values:
                return source.name
            if any(candidate.startswith(prefix) for candidate in source.values):
                return source.name
        parts = key.split(".")
        for end in range(len(parts) - 1, 0, -1):
            parent = ".".join(parts[:end])
            for source in reversed(self._sources):
                if parent in source.values:
                    return source.name
        return ""

    def enrich_error(self, error: ConfigError) -> ConfigError:
        """Attach source provenance when a module parser only knows the key."""

        if error.source or not error.key:
            return error
        source = self.source_for(error.key)
        return replace(error, source=source) if source else error

    def parse_section(
        self,
        section: str,
        parser: Callable[[Mapping[str, object]], T],
    ) -> T:
        """Build a section tree, parse it, and preserve source diagnostics."""

        try:
            return parser(self.section_tree(section))
        except ConfigError as exc:
            enriched = self.enrich_error(exc)
            if enriched is exc:
                raise
            raise enriched from exc

    def validate_sections(self, allowed: Iterable[str]) -> None:
        """Reject unknown project-level configuration sections."""

        allowed_names = frozenset(allowed)
        for source in self._sources:
            for key, value in source.values.items():
                section = key.split(".", 1)[0]
                if section not in allowed_names:
                    raise ConfigError(
                        "Unknown configuration section",
                        key=section,
                        source=source.name,
                        value=value,
                    )

    def section_tree(self, section: str) -> dict[str, object]:
        if not section:
            raise ConfigError(
                "Configuration section must be non-empty",
                key="section",
                expected="non-empty section name",
            )
        tree: dict[str, object] = {}
        prefix = f"{section}."
        for source in self._sources:
            for key, value in source.values.items():
                if key == section:
                    if isinstance(value, Mapping):
                        tree = deep_copy_mapping(cast(Mapping[str, object], value))
                        continue
                    raise ConfigError(
                        "Section key cannot be assigned a scalar value",
                        key=key,
                        source=source.name,
                        value=value,
                    )
                if not key.startswith(prefix):
                    continue
                _set_dotted_value(
                    tree,
                    key[len(prefix) :],
                    value,
                    source=source.name,
                    full_key=key,
                )
        return tree

    def load_section(self, section: str, settings_type: type[T]) -> T:
        if not is_dataclass(settings_type):
            raise ConfigError(
                "Settings type must be a dataclass type",
                key=section,
                value=settings_type,
                expected="dataclass type",
            )

        defaults = {field.name for field in fields(settings_type)}
        type_hints = get_type_hints(settings_type)
        raw_values: dict[str, tuple[object, str]] = {}
        prefix = f"{section}."

        for source in self._sources:
            for key, value in source.values.items():
                if key == section:
                    raise ConfigError(
                        "Section key cannot be assigned a scalar value",
                        key=key,
                        source=source.name,
                        value=value,
                    )
                if not key.startswith(prefix):
                    continue
                field_name = key[len(prefix) :]
                if "." in field_name:
                    raise ConfigError(
                        "Nested keys below a settings field are not supported by this settings type",
                        key=key,
                        source=source.name,
                        value=value,
                    )
                if field_name not in defaults:
                    raise ConfigError(
                        "Unknown configuration key",
                        key=key,
                        source=source.name,
                        value=value,
                    )
                raw_values[field_name] = (value, source.name)

        kwargs: dict[str, object] = {}
        for field in fields(settings_type):
            if field.name not in raw_values:
                continue
            raw_value, source_name = raw_values[field.name]
            full_key = f"{section}.{field.name}"
            kwargs[field.name] = _convert_value(
                raw_value,
                type_hints[field.name],
                key=full_key,
                source=source_name,
            )
        return settings_type(**kwargs)

def _set_dotted_value(
    tree: dict[str, object],
    dotted_key: str,
    value: object,
    *,
    source: str = "",
    full_key: str = "",
) -> None:
    parts = dotted_key.split(".")
    current = tree
    for part in parts[:-1]:
        existing = current.get(part)
        if existing is None:
            nested: dict[str, object] = {}
            current[part] = nested
            current = nested
            continue
        if not isinstance(existing, dict):
            raise ConfigError(
                "Cannot set nested configuration key below scalar value",
                key=full_key or dotted_key,
                source=source,
                value=value,
            )
        current = cast(dict[str, object], existing)
    current[parts[-1]] = value


def _convert_value(value: object, target_type: object, *, key: str, source: str) -> object:
    origin = get_origin(target_type)
    args = get_args(target_type)

    if origin is None and target_type is not None:
        return _convert_scalar(value, target_type, key=key, source=source)

    if origin is list:
        item_type = args[0] if args else str
        if isinstance(value, str):
            items: list[object] = [item.strip() for item in value.split(",") if item.strip()]
        elif isinstance(value, list):
            items = value
        else:
            raise _type_error(value, key=key, source=source, expected="list")
        return [
            _convert_value(item, item_type, key=f"{key}[]", source=source)
            for item in items
        ]

    if origin is not None and NoneType in args:
        non_none = [arg for arg in args if arg is not NoneType]
        if value is None:
            return None
        if len(non_none) == 1:
            return _convert_value(value, non_none[0], key=key, source=source)

    raise ConfigError(
        "Unsupported configuration field type",
        key=key,
        source=source,
        value=value,
        expected=str(target_type),
    )


def _convert_scalar(value: object, target_type: object, *, key: str, source: str) -> object:
    if target_type is str:
        if isinstance(value, str):
            return value
        return str(value)
    if target_type is int:
        if isinstance(value, bool):
            raise _type_error(value, key=key, source=source, expected="int")
        if not isinstance(value, (str, int, float)):
            raise _type_error(value, key=key, source=source, expected="int")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise _type_error(value, key=key, source=source, expected="int") from exc
    if target_type is float:
        if isinstance(value, bool):
            raise _type_error(value, key=key, source=source, expected="float")
        if not isinstance(value, (str, int, float)):
            raise _type_error(value, key=key, source=source, expected="float")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise _type_error(value, key=key, source=source, expected="float") from exc
    if target_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        raise _type_error(value, key=key, source=source, expected="bool")
    if target_type is Path:
        if isinstance(value, Path):
            return value
        if isinstance(value, str):
            return Path(value)
        raise _type_error(value, key=key, source=source, expected="Path")
    if isinstance(target_type, type) and issubclass(target_type, Enum):
        if isinstance(value, target_type):
            return value
        try:
            return target_type(value)
        except ValueError as exc:
            raise _type_error(value, key=key, source=source, expected=target_type.__name__) from exc
    raise ConfigError(
        "Unsupported configuration field type",
        key=key,
        source=source,
        value=value,
        expected=str(target_type),
    )


def _type_error(value: object, *, key: str, source: str, expected: str) -> ConfigError:
    return ConfigError(
        "Invalid configuration value",
        key=key,
        source=source,
        value=value,
        expected=expected,
    )
