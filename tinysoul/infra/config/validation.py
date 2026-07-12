"""Shared validation helpers for dynamic configuration tables."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .errors import ConfigError


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
