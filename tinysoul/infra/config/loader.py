"""Typed configuration loading."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
import os
from pathlib import Path
from types import NoneType
from typing import TypeVar, get_args, get_origin, get_type_hints

from .dotenv import DotenvSource, _env_mapping_to_dotted
from .errors import ConfigError
from .project_file import ProjectConfigFile
from .source import ConfigSource

T = TypeVar("T")


class ConfigLoader:
    """Load typed configuration objects from ordered configuration sources."""

    def __init__(self, sources: list[ConfigSource]) -> None:
        self._sources = list(sources)

    @classmethod
    def from_project_root(
        cls,
        root: Path,
        *,
        project_file_name: str = "tinysoul.toml",
        dotenv_name: str = ".env",
        env: Mapping[str, str] | None = None,
        overrides: Mapping[str, object] | None = None,
    ) -> "ConfigLoader":
        sources = [
            ProjectConfigFile(root / project_file_name).to_source(),
            DotenvSource(root / dotenv_name).load(),
            ConfigSource(
                name="environment",
                values=_env_mapping_to_dotted(dict(env if env is not None else os.environ)),
            ),
        ]
        if overrides:
            sources.append(ConfigSource(name="overrides", values=dict(overrides)))
        return cls(sources)

    def load_section(self, section: str, settings_type: type[T]) -> T:
        if not is_dataclass(settings_type):
            raise TypeError("settings_type must be a dataclass type")

        defaults = self._default_field_names(settings_type)
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

    @staticmethod
    def _default_field_names(settings_type: type[object]) -> set[str]:
        return {field.name for field in fields(settings_type)}


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

    if origin in (NoneType,):
        return value

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
