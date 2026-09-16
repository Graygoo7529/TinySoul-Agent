"""Immediate Shell capability settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from tinysoul.infra.config import ConfigError, reject_unknown_keys


@dataclass(frozen=True)
class ShellAdapterSettings:
    enabled: bool
    executable: str

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError(
                "Shell adapter enabled must be boolean",
                key="capabilities.shell.adapter.enabled",
                value=self.enabled,
                expected="bool",
            )
        if not isinstance(self.executable, str) or not self.executable:
            raise ConfigError(
                "Shell adapter executable must be non-empty text",
                key="capabilities.shell.adapter.executable",
                value=self.executable,
                expected="non-empty str",
            )


@dataclass(frozen=True)
class ShellSettings:
    enabled: bool = False
    max_command_chars: int = 20_000
    powershell: ShellAdapterSettings = field(
        default_factory=lambda: ShellAdapterSettings(True, "powershell")
    )
    cmd: ShellAdapterSettings = field(
        default_factory=lambda: ShellAdapterSettings(True, "cmd")
    )
    bash: ShellAdapterSettings = field(
        default_factory=lambda: ShellAdapterSettings(False, "bash")
    )

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError(
                "Shell capability enabled must be boolean",
                key="capabilities.shell.enabled",
                value=self.enabled,
                expected="bool",
            )
        if (
            isinstance(self.max_command_chars, bool)
            or not isinstance(self.max_command_chars, int)
            or self.max_command_chars <= 0
        ):
            raise ConfigError(
                "Shell command limit must be positive",
                key="capabilities.shell.max_command_chars",
                value=self.max_command_chars,
                expected="positive int",
            )
        for name in ("powershell", "cmd", "bash"):
            if not isinstance(getattr(self, name), ShellAdapterSettings):
                raise ConfigError(
                    "Shell adapter settings are invalid",
                    key=f"capabilities.shell.{name}",
                    expected="ShellAdapterSettings",
                )


def parse_shell_settings(tree: Mapping[str, object]) -> ShellSettings:
    reject_unknown_keys(
        tree,
        {"enabled", "max_command_chars", "powershell", "cmd", "bash"},
        key="capabilities.shell",
    )
    defaults = ShellSettings()
    return ShellSettings(
        enabled=_bool(tree, "enabled", defaults.enabled),
        max_command_chars=_int(
            tree,
            "max_command_chars",
            defaults.max_command_chars,
        ),
        powershell=_adapter(
            tree.get("powershell"),
            defaults.powershell,
            name="powershell",
        ),
        cmd=_adapter(tree.get("cmd"), defaults.cmd, name="cmd"),
        bash=_adapter(tree.get("bash"), defaults.bash, name="bash"),
    )


def _adapter(
    value: object,
    default: ShellAdapterSettings,
    *,
    name: str,
) -> ShellAdapterSettings:
    key = f"capabilities.shell.{name}"
    if value is None:
        tree: Mapping[str, object] = {}
    elif isinstance(value, Mapping):
        tree = cast(Mapping[str, object], value)
    else:
        raise ConfigError(
            "Shell adapter configuration must be a table",
            key=key,
            value=value,
            expected="table",
        )
    reject_unknown_keys(tree, {"enabled", "executable"}, key=key)
    executable = tree.get("executable", default.executable)
    if not isinstance(executable, str) or not executable:
        raise ConfigError(
            "Shell executable must be non-empty text",
            key=f"{key}.executable",
            value=executable,
            expected="non-empty str",
        )
    return ShellAdapterSettings(
        enabled=_bool(tree, "enabled", default.enabled, key=key),
        executable=executable,
    )


def _bool(
    tree: Mapping[str, object],
    name: str,
    default: bool,
    *,
    key: str = "capabilities.shell",
) -> bool:
    value = tree.get(name, default)
    if not isinstance(value, bool):
        raise ConfigError(
            "Shell setting must be boolean",
            key=f"{key}.{name}",
            value=value,
            expected="bool",
        )
    return value


def _int(tree: Mapping[str, object], name: str, default: int) -> int:
    value = tree.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            "Shell setting must be an integer",
            key=f"capabilities.shell.{name}",
            value=value,
            expected="int",
        )
    return value
