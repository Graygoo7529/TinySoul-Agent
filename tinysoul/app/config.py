"""App configuration models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from tinysoul.infra.config import ConfigError


@dataclass(frozen=True)
class InputCommandSettings:
    """Runtime input command words owned by the app layer."""

    exit_commands: tuple[str, ...] = ("exit", "quit")
    stop_turn_commands: tuple[str, ...] = ("stop", "cancel")

    def __post_init__(self) -> None:
        _validate_commands(self.exit_commands, key="app.exit_commands")
        _validate_commands(self.stop_turn_commands, key="app.stop_turn_commands")


@dataclass(frozen=True)
class AppSettings:
    """Process-level TinySoul app settings."""

    interactive: bool = True
    input_commands: InputCommandSettings = field(default_factory=InputCommandSettings)

    def __post_init__(self) -> None:
        if not isinstance(self.input_commands, InputCommandSettings):
            raise ConfigError(
                "App input commands must be InputCommandSettings",
                key="app.input_commands",
                value=type(self.input_commands).__name__,
                expected="InputCommandSettings",
            )


def parse_app_settings(tree: Mapping[str, object]) -> AppSettings:
    """Parse app settings from a dynamic configuration tree."""

    return AppSettings(
        interactive=_optional_bool(
            tree,
            "interactive",
            default=AppSettings.interactive,
        ),
        input_commands=InputCommandSettings(
            exit_commands=_optional_str_tuple(
                tree,
                "exit_commands",
                default=InputCommandSettings.exit_commands,
            ),
            stop_turn_commands=_optional_str_tuple(
                tree,
                "stop_turn_commands",
                default=InputCommandSettings.stop_turn_commands,
            ),
        ),
    )


def _optional_bool(
    tree: Mapping[str, object],
    name: str,
    *,
    default: bool,
) -> bool:
    value = tree.get(name, default)
    if not isinstance(value, bool):
        raise ConfigError(
            "App configuration value must be a boolean",
            key=f"app.{name}",
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
            "App configuration value must be a list of strings",
            key=f"app.{name}",
            value=value,
            expected="list[str]",
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(
                "App configuration value must contain non-empty strings",
                key=f"app.{name}",
                value=value,
                expected="list[str]",
            )
        result.append(item.strip())
    return tuple(result)


def _validate_commands(commands: tuple[str, ...], *, key: str) -> None:
    if not commands:
        raise ConfigError(
            "App command list cannot be empty",
            key=key,
            value=[],
            expected="non-empty list[str]",
        )
    seen: set[str] = set()
    for command in commands:
        if not isinstance(command, str) or not command.strip():
            raise ConfigError(
                "App command list must contain non-empty strings",
                key=key,
                value=list(commands),
                expected="non-empty list[str]",
            )
        normalized = command.strip()
        if normalized in seen:
            raise ConfigError(
                "App command list contains duplicate command",
                key=key,
                value=normalized,
            )
        seen.add(normalized)
