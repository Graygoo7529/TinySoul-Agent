"""Configured ACP targets and finite connection / delegation bounds."""

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import cast

from tinysoul.infra import DependencyChecker, DependencyRequirement
from tinysoul.infra.config import ConfigError, reject_unknown_keys
from tinysoul.infra.config.validation import (
    config_table,
    string_mapping,
    resolve_references,
)


@dataclass(frozen=True)
class AgentTarget:
    agent_id: str
    enabled: bool = False
    description: str = ""
    command: str = ""
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    env_refs: tuple[tuple[str, str], ...] = ()
    auto_approve: bool = False

    def __post_init__(self) -> None:
        if (
            not self.agent_id
            or "." in self.agent_id
            or self.agent_id.strip() != self.agent_id
        ):
            raise ConfigError(
                "ACP target identity is invalid", key="capabilities.subagent.agents"
            )
        if (
            type(self.enabled) is not bool
            or type(self.auto_approve) is not bool
            or (self.enabled and not self.command)
        ):
            raise ConfigError(
                "Enabled ACP target requires a command and typed policies",
                key=f"capabilities.subagent.agents.{self.agent_id}",
            )


@dataclass(frozen=True)
class SubagentSettings:
    agents: tuple[AgentTarget, ...] = ()
    max_connections: int = 4
    connect_timeout_seconds: float = 30.0
    max_runtime_seconds: float = 3600.0
    stop_timeout_seconds: float = 10.0
    max_output_chars: int = 1_000_000
    max_collect_chars: int = 12000
    max_brief_chars: int = 24000

    def __post_init__(self) -> None:
        for name in (
            "max_connections",
            "max_output_chars",
            "max_collect_chars",
            "max_brief_chars",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ConfigError(
                    "Subagent limit must be a positive integer",
                    key=f"capabilities.subagent.{name}",
                )
        for name in (
            "connect_timeout_seconds",
            "max_runtime_seconds",
            "stop_timeout_seconds",
        ):
            value = getattr(self, name)
            if type(value) not in {int, float} or not isfinite(value) or value <= 0:
                raise ConfigError(
                    "Subagent timeout must be finite and positive",
                    key=f"capabilities.subagent.{name}",
                )
        if len({agent.agent_id for agent in self.agents}) != len(self.agents):
            raise ConfigError(
                "ACP target identities must be unique",
                key="capabilities.subagent.agents",
            )


def parse_subagent_settings(tree: Mapping[str, object]) -> SubagentSettings:
    limits = (
        "max_connections",
        "max_output_chars",
        "max_collect_chars",
        "max_brief_chars",
    )
    timeouts = (
        "connect_timeout_seconds",
        "max_runtime_seconds",
        "stop_timeout_seconds",
    )
    reject_unknown_keys(
        tree, {"agents", *limits, *timeouts}, key="capabilities.subagent"
    )
    targets: list[AgentTarget] = []
    for identity, raw in config_table(
        tree.get("agents", {}), key="capabilities.subagent.agents"
    ).items():
        key = f"capabilities.subagent.agents.{identity}"
        row = config_table(raw, key=key)
        reject_unknown_keys(
            row,
            {
                "enabled",
                "description",
                "command",
                "args",
                "env",
                "env_refs",
                "auto_approve",
            },
            key=key,
        )
        command, description = row.get("command", ""), row.get("description", "")
        args, enabled, auto = (
            row.get("args", []),
            row.get("enabled", False),
            row.get("auto_approve", False),
        )
        if (
            not isinstance(command, str)
            or not isinstance(description, str)
            or not isinstance(args, list)
            or any(not isinstance(arg, str) for arg in args)
            or type(enabled) is not bool
            or type(auto) is not bool
        ):
            raise ConfigError("ACP target fields are invalid", key=key)
        targets.append(
            AgentTarget(
                identity,
                enabled,
                description,
                command,
                tuple(cast(list[str], args)),
                string_mapping(row.get("env", {}), key=f"{key}.env"),
                string_mapping(row.get("env_refs", {}), key=f"{key}.env_refs"),
                auto,
            )
        )
    defaults = SubagentSettings()
    numbers: dict[str, int] = {}
    for name in limits:
        value = tree.get(name, getattr(defaults, name))
        if type(value) is not int:
            raise ConfigError(
                "Subagent limit must be an integer", key=f"capabilities.subagent.{name}"
            )
        numbers[name] = value
    durations: dict[str, float] = {}
    for name in timeouts:
        value = tree.get(name, getattr(defaults, name))
        if type(value) not in {int, float}:
            raise ConfigError(
                "Subagent timeout must be numeric", key=f"capabilities.subagent.{name}"
            )
        durations[name] = cast(float, value)
    return SubagentSettings(tuple(targets), **numbers, **durations)


def validate_subagent_bindings(
    settings: SubagentSettings, environment: Mapping[str, str]
) -> dict[str, dict[str, str]]:
    """Check local readiness without starting an adapter or contacting a provider."""
    resolved: dict[str, dict[str, str]] = {}
    for target in settings.agents:
        if not target.enabled:
            continue
        key = f"capabilities.subagent.agents.{target.agent_id}"
        check = DependencyChecker().check(
            DependencyRequirement(
                "subagent", modules=("acp",), executables=(target.command,)
            )
        )
        if not check.available:
            raise ConfigError(
                "Enabled ACP target requires its executable and tinysoul[external-tools]",
                key=key,
            )
        resolved[target.agent_id] = resolve_references(
            target.env, target.env_refs, environment, key=f"{key}.env_refs"
        )
    return resolved
