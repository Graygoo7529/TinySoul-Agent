"""Process-level Agent configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tinysoul.infra.config import ConfigError, reject_unknown_keys


@dataclass(frozen=True)
class AgentSettings:
    """Bounded retention for completed root requests."""

    retained_outcomes: int = 32

    def __post_init__(self) -> None:
        if type(self.retained_outcomes) is not int or self.retained_outcomes <= 0:
            raise ConfigError(
                "Agent retained_outcomes must be positive",
                key="agent.retained_outcomes",
                value=self.retained_outcomes,
                expected="positive int",
            )


def parse_agent_settings(tree: Mapping[str, object]) -> AgentSettings:
    reject_unknown_keys(tree, {"retained_outcomes"}, key="agent")
    value = tree.get("retained_outcomes", AgentSettings.retained_outcomes)
    if type(value) is not int:
        raise ConfigError(
            "Agent retained_outcomes must be an integer",
            key="agent.retained_outcomes",
            value=value,
            expected="positive int",
        )
    return AgentSettings(retained_outcomes=value)
