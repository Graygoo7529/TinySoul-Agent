"""Loop configuration models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tinysoul.infra.config import ConfigError, reject_unknown_keys


@dataclass(frozen=True)
class DailySettings:
    """Program-level business day and archive settings."""

    timezone: str = "Asia/Shanghai"
    archive_root: Path = Path("archive")

    def __post_init__(self) -> None:
        if not isinstance(self.timezone, str) or not self.timezone:
            raise ConfigError(
                "Loop daily timezone must be a non-empty IANA timezone",
                key="loop.daily.timezone",
                value=self.timezone,
                expected="IANA timezone",
            )
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigError(
                "Loop daily timezone is unknown",
                key="loop.daily.timezone",
                value=self.timezone,
                expected="IANA timezone",
            ) from exc
        if not isinstance(self.archive_root, Path):
            raise ConfigError(
                "Loop daily archive_root must be a path",
                key="loop.daily.archive_root",
                value=self.archive_root,
                expected="path",
            )


@dataclass(frozen=True)
class LoopSettings:
    """Runtime settings owned by the loop module."""

    max_cycles_per_turn: int = 20
    phase_retry_limit: int = 2
    daily: DailySettings = field(default_factory=DailySettings)

    def __post_init__(self) -> None:
        if not isinstance(self.daily, DailySettings):
            raise ConfigError(
                "Loop daily must be DailySettings",
                key="loop.daily",
                value=self.daily,
                expected="DailySettings",
            )
        if (
            isinstance(self.max_cycles_per_turn, bool)
            or not isinstance(self.max_cycles_per_turn, int)
            or self.max_cycles_per_turn <= 0
        ):
            raise ConfigError(
                "Loop max cycles per turn must be positive",
                key="loop.max_cycles_per_turn",
                value=self.max_cycles_per_turn,
                expected="positive int",
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


def parse_loop_settings(
    tree: Mapping[str, object],
    *,
    project_root: Path | None = None,
) -> LoopSettings:
    """Parse loop settings from a dynamic configuration tree."""

    reject_unknown_keys(
        tree,
        {"max_cycles_per_turn", "phase_retry_limit", "daily"},
        key="loop",
    )
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
        daily=_parse_daily_settings(
            tree.get("daily"),
            project_root=project_root or Path.cwd(),
        ),
    )


def _parse_daily_settings(value: object, *, project_root: Path) -> DailySettings:
    if value is None:
        tree: dict[str, object] = {}
    elif isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ConfigError(
                "Loop daily setting keys must be strings",
                key="loop.daily",
                value=value,
                expected="table with string keys",
            )
        tree = {
            key: item
            for key, item in value.items()
            if isinstance(key, str)
        }
    else:
        raise ConfigError(
            "Loop daily settings must be a table",
            key="loop.daily",
            value=value,
            expected="table",
        )
    reject_unknown_keys(tree, {"timezone", "archive_root"}, key="loop.daily")
    timezone = tree.get("timezone", "Asia/Shanghai")
    if not isinstance(timezone, str):
        raise ConfigError(
            "Loop daily timezone must be a string",
            key="loop.daily.timezone",
            value=timezone,
            expected="str",
        )
    archive_value = tree.get("archive_root", "archive")
    if not isinstance(archive_value, str) or not archive_value:
        raise ConfigError(
            "Loop daily archive_root must be a non-empty path string",
            key="loop.daily.archive_root",
            value=archive_value,
            expected="str",
        )
    archive_root = Path(archive_value)
    if not archive_root.is_absolute():
        archive_root = project_root / archive_root
    return DailySettings(timezone=timezone, archive_root=archive_root)


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

