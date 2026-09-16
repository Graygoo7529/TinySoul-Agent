"""Reflection lifecycle and scheduling configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time as WallTime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.kernel.loop.config import TurnSettings, parse_turn_settings


@dataclass(frozen=True)
class ReflectionScheduleSettings:
    enabled: bool = True
    daily_time: WallTime = WallTime(hour=0, minute=15)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError(
                "Reflection schedule enabled must be a boolean",
                key="maintenance.schedule.enabled",
                value=self.enabled,
                expected="bool",
            )
        if (
            not isinstance(self.daily_time, WallTime)
            or self.daily_time.tzinfo is not None
            or self.daily_time.second
            or self.daily_time.microsecond
        ):
            raise ConfigError(
                "Reflection daily time must use local HH:MM minute precision",
                key="maintenance.schedule.daily_time",
                value=self.daily_time,
                expected="HH:MM",
            )


@dataclass(frozen=True)
class ReflectionSettings:
    timezone: str = "Asia/Shanghai"
    archive_root: Path = Path("archive")
    runtime_root: Path = Path("runtime/maintenance")
    turn: TurnSettings = field(default_factory=TurnSettings)
    schedule: ReflectionScheduleSettings = field(
        default_factory=ReflectionScheduleSettings
    )

    def __post_init__(self) -> None:
        if not isinstance(self.timezone, str) or not self.timezone:
            raise ConfigError(
                "Reflection timezone must be a non-empty IANA timezone",
                key="maintenance.timezone",
                value=self.timezone,
                expected="IANA timezone",
            )
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(
                "Reflection timezone is unknown",
                key="maintenance.timezone",
                value=self.timezone,
                expected="IANA timezone",
            ) from exc
        if not isinstance(self.archive_root, Path):
            raise ConfigError(
                "Reflection archive_root must be a path",
                key="maintenance.archive_root",
                value=self.archive_root,
                expected="path",
            )
        if not isinstance(self.runtime_root, Path):
            raise ConfigError(
                "Reflection runtime_root must be a path",
                key="maintenance.runtime_root",
                value=self.runtime_root,
                expected="path",
            )
        if not isinstance(self.turn, TurnSettings):
            raise ConfigError(
                "Reflection turn settings are invalid",
                key="maintenance.turn",
                value=self.turn,
                expected="TurnSettings",
            )
        if not isinstance(self.schedule, ReflectionScheduleSettings):
            raise ConfigError(
                "Reflection schedule is invalid",
                key="maintenance.schedule",
                value=self.schedule,
                expected="ReflectionScheduleSettings",
            )


def parse_maintenance_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path | None = None,
) -> ReflectionSettings:
    reject_unknown_keys(
        tree,
        {"timezone", "archive_root", "runtime_root", "turn", "schedule"},
        key="maintenance",
    )
    timezone = tree.get("timezone", ReflectionSettings.timezone)
    if not isinstance(timezone, str):
        raise ConfigError(
            "Reflection timezone must be a string",
            key="maintenance.timezone",
            value=timezone,
            expected="str",
        )
    archive_value = tree.get("archive_root", "archive")
    if not isinstance(archive_value, str) or not archive_value:
        raise ConfigError(
            "Reflection archive_root must be a non-empty path string",
            key="maintenance.archive_root",
            value=archive_value,
            expected="str",
        )
    archive_root = Path(archive_value)
    if not archive_root.is_absolute():
        archive_root = (project_root or Path.cwd()) / archive_root
    runtime_value = tree.get("runtime_root", "runtime/maintenance")
    if not isinstance(runtime_value, str) or not runtime_value:
        raise ConfigError(
            "Reflection runtime_root must be a non-empty path string",
            key="maintenance.runtime_root",
            value=runtime_value,
            expected="str",
        )
    runtime_root = Path(runtime_value)
    if not runtime_root.is_absolute():
        runtime_root = (project_root or Path.cwd()) / runtime_root
    return ReflectionSettings(
        timezone=timezone,
        archive_root=archive_root,
        runtime_root=runtime_root,
        turn=parse_turn_settings(tree.get("turn"), key="maintenance.turn"),
        schedule=_parse_schedule(tree.get("schedule")),
    )


def _parse_schedule(value: object) -> ReflectionScheduleSettings:
    if value is None:
        return ReflectionScheduleSettings()
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Reflection schedule must be a table",
            key="maintenance.schedule",
            value=value,
            expected="table",
        )
    table = cast(Mapping[str, object], value)
    reject_unknown_keys(table, {"enabled", "daily_time"}, key="maintenance.schedule")
    enabled = table.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigError(
            "Reflection schedule enabled must be a boolean",
            key="maintenance.schedule.enabled",
            value=enabled,
            expected="bool",
        )
    return ReflectionScheduleSettings(
        enabled=enabled,
        daily_time=_parse_wall_time(table.get("daily_time")),
    )


def _parse_wall_time(value: object) -> WallTime:
    if value is None:
        return ReflectionScheduleSettings.daily_time
    if not isinstance(value, str):
        raise ConfigError(
            "Reflection daily time must be a string",
            key="maintenance.schedule.daily_time",
            value=value,
            expected="HH:MM",
        )
    try:
        parsed = WallTime.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(
            "Reflection daily time is invalid",
            key="maintenance.schedule.daily_time",
            value=value,
            expected="HH:MM",
        ) from exc
    return parsed
