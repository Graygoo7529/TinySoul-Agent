"""Shared settings for Turn-scoped supervised process jobs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tinysoul.infra.config import ConfigError, reject_unknown_keys


ABSOLUTE_MIN_WAIT_SECONDS = 15
ABSOLUTE_MAX_WAIT_SECONDS = 60


@dataclass(frozen=True)
class SupervisedProcessSettings:
    max_mirror_files: int = 100
    max_mirror_bytes: int = 50 * 1024 * 1024
    max_mirror_file_bytes: int = 10 * 1024 * 1024
    max_candidates: int = 100
    max_candidate_read_chars: int = 12_000
    max_log_bytes: int = 2 * 1024 * 1024
    max_log_delta_chars: int = 4_000
    initial_wait_seconds: int = 10
    cycle_wait_seconds: int = 15
    min_wait_seconds: int = 15
    default_wait_seconds: int = 15
    max_wait_seconds: int = 60
    max_runtime_seconds: int = 1_800
    max_supervision_cycles: int = 32

    def __post_init__(self) -> None:
        for name in _SETTING_NAMES:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(
                    "Supervised process limit must be positive",
                    key=f"capabilities.supervised_process.{name}",
                    value=value,
                    expected="positive int",
                )
        if not (
            self.min_wait_seconds
            <= self.default_wait_seconds
            <= self.max_wait_seconds
        ):
            raise ConfigError(
                "Supervised process wait boundaries are inconsistent",
                key="capabilities.supervised_process.default_wait_seconds",
                value=self.default_wait_seconds,
                expected=(
                    f"between {self.min_wait_seconds} and {self.max_wait_seconds}"
                ),
            )
        if self.min_wait_seconds < ABSOLUTE_MIN_WAIT_SECONDS:
            raise ConfigError(
                "Supervised process model wait minimum is below its absolute boundary",
                key="capabilities.supervised_process.min_wait_seconds",
                value=self.min_wait_seconds,
                expected=f">= {ABSOLUTE_MIN_WAIT_SECONDS}",
            )
        if self.max_wait_seconds > ABSOLUTE_MAX_WAIT_SECONDS:
            raise ConfigError(
                "Supervised process model wait maximum exceeds its absolute boundary",
                key="capabilities.supervised_process.max_wait_seconds",
                value=self.max_wait_seconds,
                expected=f"<= {ABSOLUTE_MAX_WAIT_SECONDS}",
            )
        if not (
            ABSOLUTE_MIN_WAIT_SECONDS
            <= self.cycle_wait_seconds
            <= self.min_wait_seconds
        ):
            raise ConfigError(
                "Supervised process Cycle wait is inconsistent with model pacing",
                key="capabilities.supervised_process.cycle_wait_seconds",
                value=self.cycle_wait_seconds,
                expected=(
                    f"between {ABSOLUTE_MIN_WAIT_SECONDS} and "
                    f"{self.min_wait_seconds}"
                ),
            )
        if self.initial_wait_seconds > self.max_runtime_seconds:
            raise ConfigError(
                "Supervised process initial wait exceeds the runtime limit",
                key="capabilities.supervised_process.initial_wait_seconds",
                value=self.initial_wait_seconds,
                expected=f"<= {self.max_runtime_seconds}",
            )
        if self.max_mirror_file_bytes > self.max_mirror_bytes:
            raise ConfigError(
                "Supervised process mirror file limit cannot exceed total limit",
                key="capabilities.supervised_process.max_mirror_file_bytes",
                value=self.max_mirror_file_bytes,
                expected=f"<= {self.max_mirror_bytes}",
            )


_SETTING_NAMES = (
    "max_mirror_files",
    "max_mirror_bytes",
    "max_mirror_file_bytes",
    "max_candidates",
    "max_candidate_read_chars",
    "max_log_bytes",
    "max_log_delta_chars",
    "initial_wait_seconds",
    "cycle_wait_seconds",
    "min_wait_seconds",
    "default_wait_seconds",
    "max_wait_seconds",
    "max_runtime_seconds",
    "max_supervision_cycles",
)


def parse_supervised_process_settings(
    tree: Mapping[str, object],
) -> SupervisedProcessSettings:
    reject_unknown_keys(tree, set(_SETTING_NAMES), key="capabilities.supervised_process")
    defaults = SupervisedProcessSettings()
    return SupervisedProcessSettings(
        **{
            name: _int(tree, name, getattr(defaults, name))
            for name in _SETTING_NAMES
        }
    )


def _int(tree: Mapping[str, object], name: str, default: int) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Supervised process setting must be an integer",
            key=f"capabilities.supervised_process.{name}",
            value=value,
            expected="int",
        )
    return value
