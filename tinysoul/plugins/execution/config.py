"""Explicit interpreter adapters and bounded process execution settings."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.infra.network import NetworkPolicy, parse_network
from tinysoul.infra.process import OutputEncoding, ProcessEncodingError, text_encoding


class Interpreter(StrEnum):
    PYTHON = "python"
    BASH = "bash"
    POWERSHELL = "powershell"
    CMD = "cmd"


@dataclass(frozen=True)
class InterpreterSpec:
    name: Interpreter
    executable: str
    enabled: bool = True
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    output_encoding: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, Interpreter)
            or not isinstance(self.executable, str)
            or not self.executable.strip()
            or not isinstance(self.enabled, bool)
        ):
            raise ConfigError(
                "Execution interpreter is invalid", key="execution.interpreters"
            )
        encoding = self.output_encoding
        if encoding is None:
            encoding = (
                OutputEncoding.PLATFORM
                if self.name in {Interpreter.CMD, Interpreter.POWERSHELL}
                else "utf-8"
            )
        try:
            normalized = (
                OutputEncoding.PLATFORM
                if encoding == OutputEncoding.PLATFORM
                else text_encoding(encoding)
            )
        except ProcessEncodingError as exc:
            raise ConfigError(
                "Invalid output text encoding",
                key=f"execution.interpreters.{self.name}.output_encoding",
            ) from exc
        object.__setattr__(self, "output_encoding", normalized)


@dataclass(frozen=True)
class ExecutionSettings:
    enabled: bool = False
    interpreters: tuple[InterpreterSpec, ...] = (
        InterpreterSpec(Interpreter.PYTHON, "python"),
        InterpreterSpec(Interpreter.BASH, "bash", False),
        InterpreterSpec(Interpreter.POWERSHELL, "powershell", False),
        InterpreterSpec(Interpreter.CMD, "cmd", False),
    )
    max_runtime_seconds: int = 1800
    max_output_bytes: int = 2 * 1024 * 1024
    max_collect_chars: int = 4096
    max_source_chars: int = 102400
    max_command_chars: int = 20480
    max_args: int = 64
    max_arg_chars: int = 4096
    network: NetworkPolicy = field(default_factory=NetworkPolicy)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError(
                "Execution enabled must be boolean", key="execution.enabled"
            )
        if (
            not isinstance(self.interpreters, tuple)
            or any(not isinstance(item, InterpreterSpec) for item in self.interpreters)
            or len({item.name for item in self.interpreters}) != len(self.interpreters)
        ):
            raise ConfigError(
                "Execution interpreters must have unique identities",
                key="execution.interpreters",
            )
        for name in _LIMITS:
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ConfigError(
                    "Execution limit must be a positive integer",
                    key=f"execution.{name}",
                )


_LIMITS = (
    "max_runtime_seconds",
    "max_output_bytes",
    "max_collect_chars",
    "max_source_chars",
    "max_command_chars",
    "max_args",
    "max_arg_chars",
)


def parse_execution_settings(tree: Mapping[str, object]) -> ExecutionSettings:
    reject_unknown_keys(
        tree, {"enabled", "interpreters", "network", *_LIMITS}, key="execution"
    )
    defaults = ExecutionSettings()
    enabled = tree.get("enabled", defaults.enabled)
    if not isinstance(enabled, bool):
        raise ConfigError("Execution enabled must be boolean", key="execution.enabled")
    limits: dict[str, int] = {}
    for name in _LIMITS:
        value = tree.get(name, getattr(defaults, name))
        if type(value) is not int:
            raise ConfigError(
                "Execution limit must be an integer", key=f"execution.{name}"
            )
        limits[name] = value
    adapters = tree.get("interpreters", {})
    if not isinstance(adapters, Mapping):
        raise ConfigError(
            "Execution interpreters must be a table", key="execution.interpreters"
        )
    if set(adapters) - {item.value for item in Interpreter}:
        raise ConfigError("Unknown execution interpreter", key="execution.interpreters")
    parsed: list[InterpreterSpec] = []
    for default in defaults.interpreters:
        raw = adapters.get(default.name.value, {})
        key = f"execution.interpreters.{default.name}"
        if not isinstance(raw, Mapping) or set(raw) - {
            "enabled",
            "executable",
            "network",
            "output_encoding",
        }:
            raise ConfigError("Invalid interpreter configuration", key=key)
        executable, selected = (
            raw.get("executable", default.executable),
            raw.get("enabled", default.enabled),
        )
        if not isinstance(executable, str) or not isinstance(selected, bool):
            raise ConfigError("Invalid interpreter fields", key=key)
        encoding = raw.get("output_encoding", default.output_encoding)
        if not isinstance(encoding, str):
            raise ConfigError("Output encoding must be text", key=f"{key}.output_encoding")
        parsed.append(
            InterpreterSpec(
                default.name,
                executable,
                selected,
                parse_network(raw.get("network", {}), key=f"{key}.network"),
                encoding,
            )
        )
    return ExecutionSettings(
        network=parse_network(tree.get("network", {}), key="execution.network"),
        enabled=enabled,
        interpreters=tuple(parsed),
        **limits,
    )
