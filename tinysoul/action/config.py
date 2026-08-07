"""Action module project settings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from tinysoul.infra.config import ConfigError, reject_unknown_keys


@dataclass(frozen=True)
class ActionSettings:
    """Project-owned Action runtime defaults applied at catalog load."""

    llm_action_timeout_seconds: float = 600.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.llm_action_timeout_seconds, bool)
            or not isinstance(self.llm_action_timeout_seconds, (int, float))
            or self.llm_action_timeout_seconds <= 0
        ):
            raise ConfigError(
                "Action llm_action_timeout_seconds must be positive",
                key="action.llm_action_timeout_seconds",
                value=self.llm_action_timeout_seconds,
                expected="positive number",
            )
        object.__setattr__(
            self,
            "llm_action_timeout_seconds",
            float(self.llm_action_timeout_seconds),
        )


def parse_action_settings(tree: Mapping[str, object]) -> ActionSettings:
    """Parse Action settings from a dynamic configuration tree."""

    reject_unknown_keys(tree, {"llm_action_timeout_seconds"}, key="action")
    value = tree.get(
        "llm_action_timeout_seconds",
        ActionSettings.llm_action_timeout_seconds,
    )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            "Action llm_action_timeout_seconds must be a number",
            key="action.llm_action_timeout_seconds",
            value=value,
            expected="positive number",
        )
    return ActionSettings(llm_action_timeout_seconds=float(value))
