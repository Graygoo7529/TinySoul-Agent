"""App configuration models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time as WallTime
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.runtime import ObservationLevel


@dataclass(frozen=True)
class InputCommandSettings:
    """Runtime input command words owned by the app layer."""

    exit_commands: tuple[str, ...] = ("exit", "quit")
    stop_turn_commands: tuple[str, ...] = ("stop", "cancel")

    def __post_init__(self) -> None:
        _validate_commands(self.exit_commands, key="app.exit_commands")
        _validate_commands(self.stop_turn_commands, key="app.stop_turn_commands")


@dataclass(frozen=True)
class OutputSettings:
    """Observation filtering and bounded model-detail rendering settings."""

    mode: ObservationLevel = ObservationLevel.NORMAL
    model_max_chars: int = 20000

    def __post_init__(self) -> None:
        if not isinstance(self.mode, ObservationLevel):
            raise ConfigError(
                "App output mode is invalid",
                key="app.output.mode",
                value=self.mode,
                expected="normal | verbose | model",
            )
        if (
            isinstance(self.model_max_chars, bool)
            or not isinstance(self.model_max_chars, int)
            or self.model_max_chars <= 0
        ):
            raise ConfigError(
                "App output model_max_chars must be positive",
                key="app.output.model_max_chars",
                value=self.model_max_chars,
                expected="positive int",
            )


@dataclass(frozen=True)
class SchedulerSettings:
    """Built-in Program event scheduler settings."""

    enabled: bool = True
    home_maintenance_time: WallTime = WallTime(hour=0, minute=5)
    memory_maintenance_time: WallTime = WallTime(hour=0, minute=15)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError(
                "App scheduler enabled must be a boolean",
                key="app.scheduler.enabled",
                value=self.enabled,
                expected="bool",
            )
        for name in ("home_maintenance_time", "memory_maintenance_time"):
            value = getattr(self, name)
            if not isinstance(value, WallTime) or value.tzinfo is not None:
                raise ConfigError(
                    "App scheduler time must be a local wall time",
                    key=f"app.scheduler.{name}",
                    value=value,
                    expected="HH:MM",
                )
            if value.second or value.microsecond:
                raise ConfigError(
                    "App scheduler time must use minute precision",
                    key=f"app.scheduler.{name}",
                    value=value.isoformat(),
                    expected="HH:MM",
                )
        if self.home_maintenance_time >= self.memory_maintenance_time:
            raise ConfigError(
                "Home Maintenance must be scheduled before Memory Maintenance",
                key="app.scheduler.memory_maintenance_time",
                value=self.memory_maintenance_time.isoformat(timespec="minutes"),
                expected="time after home_maintenance_time",
            )


@dataclass(frozen=True)
class AppSettings:
    """Process-level TinySoul app settings."""

    interactive: bool = True
    input_commands: InputCommandSettings = field(default_factory=InputCommandSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)
    retained_turn_outcomes: int = 32

    def __post_init__(self) -> None:
        if not isinstance(self.input_commands, InputCommandSettings):
            raise ConfigError(
                "App input commands must be InputCommandSettings",
                key="app.input_commands",
                value=type(self.input_commands).__name__,
                expected="InputCommandSettings",
            )
        if not isinstance(self.output, OutputSettings):
            raise ConfigError(
                "App output settings must be OutputSettings",
                key="app.output",
                value=type(self.output).__name__,
                expected="OutputSettings",
            )
        if not isinstance(self.scheduler, SchedulerSettings):
            raise ConfigError(
                "App scheduler settings must be SchedulerSettings",
                key="app.scheduler",
                value=type(self.scheduler).__name__,
                expected="SchedulerSettings",
            )
        if (
            isinstance(self.retained_turn_outcomes, bool)
            or not isinstance(self.retained_turn_outcomes, int)
            or self.retained_turn_outcomes <= 0
        ):
            raise ConfigError(
                "App retained_turn_outcomes must be positive",
                key="app.retained_turn_outcomes",
                value=self.retained_turn_outcomes,
                expected="positive int",
            )


def parse_app_settings(tree: Mapping[str, object]) -> AppSettings:
    """Parse app settings from a dynamic configuration tree."""

    reject_unknown_keys(
        tree,
        {
            "interactive",
            "exit_commands",
            "stop_turn_commands",
            "output",
            "scheduler",
            "retained_turn_outcomes",
        },
        key="app",
    )
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
        output=_parse_output_settings(tree.get("output")),
        scheduler=_parse_scheduler_settings(tree.get("scheduler")),
        retained_turn_outcomes=_optional_int(
            tree,
            "retained_turn_outcomes",
            default=AppSettings.retained_turn_outcomes,
        ),
    )


def _parse_output_settings(value: object) -> OutputSettings:
    if value is None:
        return OutputSettings()
    if not isinstance(value, Mapping):
        raise ConfigError(
            "App output configuration must be a table",
            key="app.output",
            value=value,
            expected="table",
        )
    table = cast(Mapping[str, object], value)
    reject_unknown_keys(table, {"mode", "model_max_chars"}, key="app.output")
    raw_mode = table.get("mode", ObservationLevel.NORMAL.value)
    if not isinstance(raw_mode, str):
        raise ConfigError(
            "App output mode must be a string",
            key="app.output.mode",
            value=raw_mode,
            expected="normal | verbose | model",
        )
    try:
        mode = ObservationLevel(raw_mode)
    except ValueError as exc:
        raise ConfigError(
            "App output mode is invalid",
            key="app.output.mode",
            value=raw_mode,
            expected="normal | verbose | model",
        ) from exc
    return OutputSettings(
        mode=mode,
        model_max_chars=_optional_int(
            table,
            "model_max_chars",
            default=OutputSettings.model_max_chars,
            key_prefix="app.output",
        ),
    )


def _parse_scheduler_settings(value: object) -> SchedulerSettings:
    if value is None:
        return SchedulerSettings()
    if not isinstance(value, Mapping):
        raise ConfigError(
            "App scheduler configuration must be a table",
            key="app.scheduler",
            value=value,
            expected="table",
        )
    table = cast(Mapping[str, object], value)
    reject_unknown_keys(
        table,
        {"enabled", "home_maintenance_time", "memory_maintenance_time"},
        key="app.scheduler",
    )
    return SchedulerSettings(
        enabled=_table_bool(table, "enabled", SchedulerSettings.enabled),
        home_maintenance_time=_wall_time(
            table,
            "home_maintenance_time",
            SchedulerSettings.home_maintenance_time,
        ),
        memory_maintenance_time=_wall_time(
            table,
            "memory_maintenance_time",
            SchedulerSettings.memory_maintenance_time,
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


def _table_bool(
    table: Mapping[str, object],
    name: str,
    default: bool,
) -> bool:
    value = table.get(name, default)
    if not isinstance(value, bool):
        raise ConfigError(
            "App scheduler configuration value must be a boolean",
            key=f"app.scheduler.{name}",
            value=value,
            expected="bool",
        )
    return value


def _wall_time(
    table: Mapping[str, object],
    name: str,
    default: WallTime,
) -> WallTime:
    value = table.get(name)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ConfigError(
            "App scheduler time must be a string",
            key=f"app.scheduler.{name}",
            value=value,
            expected="HH:MM",
        )
    try:
        parsed = WallTime.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(
            "App scheduler time is invalid",
            key=f"app.scheduler.{name}",
            value=value,
            expected="HH:MM",
        ) from exc
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise ConfigError(
            "App scheduler time must use HH:MM without seconds or timezone",
            key=f"app.scheduler.{name}",
            value=value,
            expected="HH:MM",
        )
    return parsed


def _optional_int(
    tree: Mapping[str, object],
    name: str,
    *,
    default: int,
    key_prefix: str = "app",
) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "App configuration value must be an integer",
            key=f"{key_prefix}.{name}",
            value=value,
            expected="int",
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
