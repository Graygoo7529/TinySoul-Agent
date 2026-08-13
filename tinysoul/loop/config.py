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
                key="turn.max_cycles",
                value=self.max_cycles,
                expected="positive int",
            )


@dataclass(frozen=True)
class CycleSettings:
    """Task-profile routing shared by every reusable Cycle."""

    phase1_task_profile: str = "framework"
    phase2_task_profile: str = "framework"

    def __post_init__(self) -> None:
        _validate_task_profile(
            self.phase1_task_profile,
            key="loop.cycle.phase1_task_profile",
        )
        _validate_task_profile(
            self.phase2_task_profile,
            key="loop.cycle.phase2_task_profile",
        )


@dataclass(frozen=True)
class LoopSettings:
    """Runtime settings owned by the Loop module."""

    cycle: CycleSettings = field(default_factory=CycleSettings)
    user: TurnSettings = field(default_factory=TurnSettings)

    def __post_init__(self) -> None:
        if not isinstance(self.cycle, CycleSettings):
            raise ConfigError(
                "Loop cycle settings must be CycleSettings",
                key="loop.cycle",
                value=self.cycle,
                expected="CycleSettings",
            )
        if not isinstance(self.user, TurnSettings):
            raise ConfigError(
                "Loop user settings must be TurnSettings",
                key="loop.user",
                value=self.user,
                expected="TurnSettings",
            )


def parse_loop_settings(tree: Mapping[str, object]) -> LoopSettings:
    """Parse Loop settings from a dynamic configuration tree."""

    reject_unknown_keys(
        tree,
        {"cycle", "user"},
        key="loop",
    )
    return LoopSettings(
        cycle=parse_cycle_settings(tree.get("cycle"), key="loop.cycle"),
        user=parse_turn_settings(tree.get("user"), key="loop.user"),
    )


def parse_cycle_settings(value: object, *, key: str) -> CycleSettings:
    if value is None:
        return CycleSettings()
    if not isinstance(value, Mapping):
        raise ConfigError(
            "Loop Cycle settings must be a table",
            key=key,
            value=value,
            expected="table",
        )
    table = cast(Mapping[str, object], value)
    reject_unknown_keys(
        table,
        {"phase1_task_profile", "phase2_task_profile"},
        key=key,
    )
    return CycleSettings(
        phase1_task_profile=_optional_task_profile(
            table,
            "phase1_task_profile",
            default=CycleSettings.phase1_task_profile,
            key=f"{key}.phase1_task_profile",
        ),
        phase2_task_profile=_optional_task_profile(
            table,
            "phase2_task_profile",
            default=CycleSettings.phase2_task_profile,
            key=f"{key}.phase2_task_profile",
        ),
    )


def parse_turn_settings(value: object, *, key: str) -> TurnSettings:
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


def _optional_task_profile(
    tree: Mapping[str, object],
    name: str,
    *,
    default: str,
    key: str,
) -> str:
    value = tree.get(name, default)
    _validate_task_profile(value, key=key)
    return cast(str, value)


def _validate_task_profile(value: object, *, key: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "." in value
    ):
        raise ConfigError(
            "Loop task profile ID must be a non-empty identifier without dots or outer whitespace",
            key=key,
            value=value,
            expected="task profile ID",
        )


def validate_cycle_task_profiles(
    settings: CycleSettings,
    *,
    task_profiles: tuple[str, ...],
) -> None:
    """Validate Cycle phase references against the configured LLM task table."""

    profiles = frozenset(task_profiles)
    for name, profile in (
        ("phase1_task_profile", settings.phase1_task_profile),
        ("phase2_task_profile", settings.phase2_task_profile),
    ):
        if profile not in profiles:
            raise ConfigError(
                "Loop Cycle phase references an unknown task profile",
                key=f"loop.cycle.{name}",
                value=profile,
            )
