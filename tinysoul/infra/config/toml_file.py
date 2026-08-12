"""Single TOML configuration file support."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast
import tomllib

from .errors import ConfigError
from .source import ConfigSource, ConfigSourceKind
from ..filesystem import atomic_write_text


class ConfigFileToml:
    """Readable and writable TOML configuration file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, object] = {}
        if self.path.exists():
            self._data = _string_key_mapping(
                tomllib.loads(self.path.read_text(encoding="utf-8"))
            )

    @property
    def data(self) -> dict[str, object]:
        return deep_copy_mapping(self._data)

    def to_source(self) -> ConfigSource:
        return ConfigSource(
            name=str(self.path),
            values=flatten_mapping(self._data),
            kind=ConfigSourceKind.PROJECT_TOML,
            path=self.path,
        )

    def set_value(self, dotted_key: str, value: object) -> None:
        if not dotted_key:
            raise ConfigError(
                "Configuration key must be non-empty",
                key="config",
                source=str(self.path),
                expected="non-empty dotted key",
            )
        parts = dotted_key.split(".")
        current: dict[str, object] = self._data
        for part in parts[:-1]:
            existing = current.get(part)
            if existing is None:
                nested: dict[str, object] = {}
                current[part] = nested
                current = nested
                continue
            if not isinstance(existing, dict):
                raise ConfigError(
                    "Cannot set nested key below scalar",
                    key=dotted_key,
                    value=part,
                    source=str(self.path),
                    expected="table",
                )
            current = cast(dict[str, object], existing)
        current[parts[-1]] = value

    def delete_value(self, dotted_key: str) -> None:
        if not dotted_key:
            raise ConfigError(
                "Configuration key must be non-empty",
                key="config",
                source=str(self.path),
                expected="non-empty dotted key",
            )
        parts = dotted_key.split(".")
        current: dict[str, object] = self._data
        parents: list[tuple[dict[str, object], str]] = []
        for part in parts[:-1]:
            existing = current.get(part)
            if existing is None:
                return
            if not isinstance(existing, dict):
                raise ConfigError(
                    "Cannot delete nested key below scalar",
                    key=dotted_key,
                    value=part,
                    source=str(self.path),
                    expected="table",
                )
            parents.append((current, part))
            current = cast(dict[str, object], existing)
        current.pop(parts[-1], None)
        for parent, part in reversed(parents):
            value = parent.get(part)
            if isinstance(value, dict) and not value:
                parent.pop(part, None)
                continue
            break

    def render(self) -> str:
        return _to_toml(self._data)

    def save(self) -> None:
        atomic_write_text(self.path, self.render())


def flatten_mapping(data: Mapping[str, object], prefix: str = "") -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            result.update(
                flatten_mapping(_string_key_mapping(cast(Mapping[str, object], value)), dotted)
            )
        else:
            result[dotted] = value
    return result


def deep_copy_mapping(data: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in data.items():
        result[str(key)] = _copy_value(value)
    return result


def merge_trees(
    base: Mapping[str, object],
    overlay: Mapping[str, object],
) -> dict[str, object]:
    result = deep_copy_mapping(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if existing is None:
            result[key] = _copy_value(value)
            continue
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            result[key] = merge_trees(
                _string_key_mapping(cast(Mapping[str, object], existing)),
                _string_key_mapping(cast(Mapping[str, object], value)),
            )
            continue
        if isinstance(existing, Mapping) or isinstance(value, Mapping):
            raise ConfigError(
                "Cannot merge table and scalar",
                key=str(key),
                value=key,
                expected="matching value kinds",
            )
        result[key] = value
    return result


def _copy_value(value: object) -> object:
    if isinstance(value, Mapping):
        return deep_copy_mapping(_string_key_mapping(cast(Mapping[str, object], value)))
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    return value


def _to_toml(data: Mapping[str, object]) -> str:
    lines: list[str] = []
    _write_section(lines, [], data)
    return "\n".join(lines).rstrip() + "\n"


def _write_section(
    lines: list[str], path: list[str], data: Mapping[str, object]
) -> None:
    scalar_items = [(key, value) for key, value in data.items() if not isinstance(value, Mapping)]
    nested_items = [(key, value) for key, value in data.items() if isinstance(value, Mapping)]

    if path:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"[{'.'.join(path)}]")

    for key, value in sorted(scalar_items):
        lines.append(f"{key} = {_format_toml_value(value)}")

    for key, value in sorted(nested_items):
        _write_section(
            lines,
            [*path, str(key)],
            _string_key_mapping(cast(Mapping[str, object], value)),
        )


def _string_key_mapping(data: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ConfigError(
                "Configuration keys must be strings",
                key="config",
                value=repr(key),
                expected="str",
            )
        result[key] = value
    return result


def _format_toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    if isinstance(value, Path):
        return _quote(str(value))
    if isinstance(value, str):
        return _quote(value)
    raise ConfigError(
        "Unsupported TOML value type",
        key="config",
        value=type(value).__name__,
        expected="bool | int | float | str | list | Path",
    )


def _quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'
