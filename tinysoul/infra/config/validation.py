"""Shared validation helpers for dynamic configuration tables."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .errors import ConfigError
from typing import cast


def reject_unknown_keys(
    table: Mapping[str, object],
    allowed: Iterable[str],
    *,
    key: str,
) -> None:
    """Reject table keys not owned by the current configuration parser."""

    allowed_keys = frozenset(allowed)
    for name, value in table.items():
        if name not in allowed_keys:
            raise ConfigError(
                "Unknown configuration key",
                key=f"{key}.{name}" if key else name,
                value=value,
            )


def config_table(value: object, *, key: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(name, str) for name in value
    ):
        raise ConfigError("Configuration requires a table", key=key)
    return cast(Mapping[str, object], value)


def string_mapping(value: object, *, key: str) -> tuple[tuple[str, str], ...]:
    table = config_table(value, key=key)
    if any(not isinstance(item, str) for item in table.values()):
        raise ConfigError("Configuration requires text values", key=key)
    return tuple((name, cast(str, item)) for name, item in table.items())


def resolve_references(
    values: tuple[tuple[str, str], ...],
    references: tuple[tuple[str, str], ...],
    environment: Mapping[str, str],
    *,
    key: str,
) -> dict[str, str]:
    result = dict(values)
    for name, reference in references:
        if not environment.get(reference):
            raise ConfigError("Configured credential reference is unavailable", key=key)
        result[name] = environment[reference]
    return result
