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
    exit_commands: tuple[str, ...] = ("exit", "quit")
    stop_turn_commands: tuple[str, ...] = ("stop", "cancel")
    interactive: bool = True

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
        _validate_commands(self.exit_commands, key="loop.exit_commands")
        _validate_commands(self.stop_turn_commands, key="loop.stop_turn_commands")


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
        exit_commands=_optional_str_tuple(
            tree,
            "exit_commands",
            default=LoopSettings.exit_commands,
        ),
        stop_turn_commands=_optional_str_tuple(
            tree,
            "stop_turn_commands",
            default=LoopSettings.stop_turn_commands,
        ),
        interactive=_optional_bool(
            tree,
            "interactive",
            default=LoopSettings.interactive,
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


def _optional_bool(
    tree: Mapping[str, object],
    name: str,
    *,
    default: bool,
) -> bool:
    value = tree.get(name, default)
    if not isinstance(value, bool):
        raise ConfigError(
            "Loop configuration value must be a boolean",
            key=f"loop.{name}",
            value=value,
            expected="bool",
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
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if not isinstance(value, list):
        raise ConfigError(
            "Loop configuration value must be a list of strings",
            key=f"loop.{name}",
            value=value,
            expected="list[str]",
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(
                "Loop configuration value must contain non-empty strings",
                key=f"loop.{name}",
                value=value,
                expected="list[str]",
            )
        result.append(item.strip())
    return tuple(result)


def _validate_commands(commands: tuple[str, ...], *, key: str) -> None:
    if not commands:
        raise ConfigError(
            "Loop command list cannot be empty",
            key=key,
            value=[],
            expected="non-empty list[str]",
        )
    seen: set[str] = set()
    for command in commands:
        if not isinstance(command, str) or not command.strip():
            raise ConfigError(
                "Loop command list must contain non-empty strings",
                key=key,
                value=list(commands),
                expected="non-empty list[str]",
            )
        normalized = command.strip()
        if normalized in seen:
            raise ConfigError(
                "Loop command list contains duplicate command",
                key=key,
                value=normalized,
            )
        seen.add(normalized)
