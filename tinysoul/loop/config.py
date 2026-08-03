"""Loop configuration models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys


@dataclass(frozen=True)
class TurnSettings:
    """Cycle budget for one kind of Turn."""

    max_cycles: int = 20

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_cycles, bool)
            or not isinstance(self.max_cycles, int)
            or self.max_cycles <= 0
        ):
            raise ConfigError(
                "Turn max_cycles must be positive",
                key="loop.turn.max_cycles",
                value=self.max_cycles,
                expected="positive int",
            )


@dataclass(frozen=True)
class LoopSettings:
    """Runtime settings owned by the Loop module."""

    user: TurnSettings = field(default_factory=TurnSettings)
    maintenance: TurnSettings = field(default_factory=TurnSettings)
    phase_retry_limit: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.user, TurnSettings):
            raise ConfigError(
                "Loop user settings must be TurnSettings",
                key="loop.user",
                value=self.user,
                expected="TurnSettings",
            )
        if not isinstance(self.maintenance, TurnSettings):
            raise ConfigError(
                "Loop maintenance settings must be TurnSettings",
                key="loop.maintenance",
                value=self.maintenance,
                expected="TurnSettings",
            )
        if (
            isinstance(self.phase_retry_limit, bool)
            or not isinstance(self.phase_retry_limit, int)
            or self.phase_retry_limit <= 0
        ):
            raise ConfigError(
                "Loop phase retry limit must be positive",
                key="loop.phase_retry_limit",
                value=self.phase_retry_limit,
                expected="positive int",
            )


def parse_loop_settings(tree: Mapping[str, object]) -> LoopSettings:
    """Parse Loop settings from a dynamic configuration tree."""

    reject_unknown_keys(
        tree,
        {"user", "maintenance", "phase_retry_limit"},
        key="loop",
    )
    return LoopSettings(
        user=_parse_turn_settings(tree.get("user"), key="loop.user"),
        maintenance=_parse_turn_settings(
            tree.get("maintenance"),
            key="loop.maintenance",
        ),
        phase_retry_limit=_optional_int(
            tree,
            "phase_retry_limit",
            default=LoopSettings.phase_retry_limit,
            key="loop.phase_retry_limit",
        ),
    )


def _parse_turn_settings(value: object, *, key: str) -> TurnSettings:
    if value is None:
        return TurnSettings()
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Loop Turn settings must be a table",
            key=key,
            value=value,
            expected="table",
        )
    table = cast(Mapping[str, object], value)
    reject_unknown_keys(table, {"max_cycles"}, key=key)
    return TurnSettings(
        max_cycles=_optional_int(
            table,
            "max_cycles",
            default=TurnSettings.max_cycles,
            key=f"{key}.max_cycles",
        )
    )


def _optional_int(
    tree: Mapping[str, object],
    name: str,
    *,
    default: int,
    key: str,
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Loop configuration value must be an integer",
            key=key,
            value=value,
            expected="int",
        )
    return value
