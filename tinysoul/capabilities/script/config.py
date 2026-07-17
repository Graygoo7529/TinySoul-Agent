"""Script capability settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys


@dataclass(frozen=True)
class ScriptLanguageSettings:
    enabled: bool
    executable: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError(
                "Script language enabled must be boolean",
                key="capabilities.script.language.enabled",
                value=self.enabled,
                expected="bool",
            )
        if not isinstance(self.executable, str):
            raise ConfigError(
                "Script language executable must be text",
                key="capabilities.script.language.executable",
                value=self.executable,
                expected="str",
            )


@dataclass(frozen=True)
class ScriptSettings:
    enabled: bool = True
    python: ScriptLanguageSettings = field(
        default_factory=lambda: ScriptLanguageSettings(enabled=True)
    )
    bash: ScriptLanguageSettings = field(
        default_factory=lambda: ScriptLanguageSettings(enabled=False, executable="bash")
    )
    max_source_chars: int = 100_000
    max_args: int = 32
    max_arg_chars: int = 1_000
    max_mirror_files: int = 100
    max_mirror_bytes: int = 50 * 1024 * 1024
    max_mirror_file_bytes: int = 10 * 1024 * 1024
    max_candidates: int = 100
    max_candidate_read_chars: int = 12_000
    max_log_bytes: int = 2 * 1024 * 1024
    max_log_delta_chars: int = 4_000
    initial_wait_seconds: int = 10
    min_wait_seconds: int = 5
    default_wait_seconds: int = 15
    max_wait_seconds: int = 60
    max_runtime_seconds: int = 1_800
    max_supervision_cycles: int = 32

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError(
                "Script capability enabled must be boolean",
                key="capabilities.script.enabled",
                value=self.enabled,
                expected="bool",
            )
        if not isinstance(self.python, ScriptLanguageSettings) or not isinstance(
            self.bash, ScriptLanguageSettings
        ):
            raise ConfigError(
                "Script language settings are invalid",
                key="capabilities.script",
                expected="ScriptLanguageSettings",
            )
        for name in (
            "max_source_chars",
            "max_args",
            "max_arg_chars",
            "max_mirror_files",
            "max_mirror_bytes",
            "max_mirror_file_bytes",
            "max_candidates",
            "max_candidate_read_chars",
            "max_log_bytes",
            "max_log_delta_chars",
            "initial_wait_seconds",
            "min_wait_seconds",
            "default_wait_seconds",
            "max_wait_seconds",
            "max_runtime_seconds",
            "max_supervision_cycles",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(
                    "Script capability limit must be positive",
                    key=f"capabilities.script.{name}",
                    value=value,
                    expected="positive int",
                )
        if not (
            self.min_wait_seconds
            <= self.default_wait_seconds
            <= self.max_wait_seconds
        ):
            raise ConfigError(
                "Script wait boundaries are inconsistent",
                key="capabilities.script.default_wait_seconds",
                value=self.default_wait_seconds,
                expected=(
                    f"between {self.min_wait_seconds} and {self.max_wait_seconds}"
                ),
            )
        if self.initial_wait_seconds > self.max_wait_seconds:
            raise ConfigError(
                "Script initial wait cannot exceed max wait",
                key="capabilities.script.initial_wait_seconds",
                value=self.initial_wait_seconds,
                expected=f"<= {self.max_wait_seconds}",
            )
        if self.max_mirror_file_bytes > self.max_mirror_bytes:
            raise ConfigError(
                "Script mirror file limit cannot exceed total mirror limit",
                key="capabilities.script.max_mirror_file_bytes",
                value=self.max_mirror_file_bytes,
                expected=f"<= {self.max_mirror_bytes}",
            )


def parse_script_settings(tree: Mapping[str, object]) -> ScriptSettings:
    defaults = ScriptSettings()
    keys = {
        "enabled",
        "python",
        "bash",
        "max_source_chars",
        "max_args",
        "max_arg_chars",
        "max_mirror_files",
        "max_mirror_bytes",
        "max_mirror_file_bytes",
        "max_candidates",
        "max_candidate_read_chars",
        "max_log_bytes",
        "max_log_delta_chars",
        "initial_wait_seconds",
        "min_wait_seconds",
        "default_wait_seconds",
        "max_wait_seconds",
        "max_runtime_seconds",
        "max_supervision_cycles",
    }
    reject_unknown_keys(tree, keys, key="capabilities.script")
    values = {
        name: _int(tree, name, cast(int, getattr(defaults, name)))
        for name in keys
        if name not in {"enabled", "python", "bash"}
    }
    return ScriptSettings(
        enabled=_bool(tree, "enabled", defaults.enabled),
        python=_language(tree.get("python"), defaults.python, name="python"),
        bash=_language(tree.get("bash"), defaults.bash, name="bash"),
        **values,
    )


def _language(
    value: object,
    default: ScriptLanguageSettings,
    *,
    name: str,
) -> ScriptLanguageSettings:
    key = f"capabilities.script.{name}"
    if value is None:
        tree: Mapping[str, object] = {}
    elif isinstance(value, Mapping):
        tree = cast(Mapping[str, object], value)
    else:
        raise ConfigError(
            "Script language configuration must be a table",
            key=key,
            value=value,
            expected="table",
        )
    reject_unknown_keys(tree, {"enabled", "executable"}, key=key)
    executable = tree.get("executable", default.executable)
    if not isinstance(executable, str):
        raise ConfigError(
            "Script executable must be text",
            key=f"{key}.executable",
            value=executable,
            expected="str",
        )
    return ScriptLanguageSettings(
        enabled=_bool(tree, "enabled", default.enabled, key=key),
        executable=executable,
    )


def _bool(
    tree: Mapping[str, object],
    name: str,
    default: bool,
    *,
    key: str = "capabilities.script",
) -> bool:
    value = tree.get(name, default)
    if not isinstance(value, bool):
        raise ConfigError(
            "Script setting must be boolean",
            key=f"{key}.{name}",
            value=value,
            expected="bool",
        )
    return value


def _int(tree: Mapping[str, object], name: str, default: int) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Script setting must be an integer",
            key=f"capabilities.script.{name}",
            value=value,
            expected="int",
        )
    return value
