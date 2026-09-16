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
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ConfigError(
                    "Script capability limit must be positive",
                    key=f"capabilities.script.{name}",
                    value=value,
                    expected="positive int",
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
