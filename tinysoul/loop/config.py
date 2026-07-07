"""Loop configuration models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tinysoul.infra.config import ConfigError


@dataclass(frozen=True)
class LoopSettings:
    """Runtime settings owned by the loop module."""

    max_cycles_per_turn: int = 8
    phase_retry_limit: int = 2

    def __post_init__(self) -> None:
        if self.max_cycles_per_turn <= 0:
            raise ConfigError(
                "Loop max cycles per turn must be positive",
                key="loop.max_cycles_per_turn",
                value=self.max_cycles_per_turn,
                expected="positive int",
            )
        if self.phase_retry_limit <= 0:
            raise ConfigError(
                "Loop phase retry limit must be positive",
                key="loop.phase_retry_limit",
                value=self.phase_retry_limit,
                expected="positive int",
            )


def parse_loop_settings(tree: Mapping[str, object]) -> LoopSettings:
    """Parse loop settings from a dynamic configuration tree."""

    return LoopSettings(
        max_cycles_per_turn=_optional_int(
            tree,
            "max_cycles_per_turn",
            default=LoopSettings.max_cycles_per_turn,
        ),
        phase_retry_limit=_optional_int(
            tree,
            "phase_retry_limit",
            default=LoopSettings.phase_retry_limit,
        ),
    )


def _optional_int(
    tree: Mapping[str, object],
    name: str,
    *,
    default: int,
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Loop configuration value must be an integer",
            key=f"loop.{name}",
            value=value,
            expected="int",
        )
    return value

