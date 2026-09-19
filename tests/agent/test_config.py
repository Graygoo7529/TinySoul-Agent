from __future__ import annotations

import pytest

from tinysoul.agent.config import AgentSettings
from tinysoul.agent.config import parse_agent_settings
from tinysoul.infra.config import ConfigError


def test_parse_agent_settings_defaults() -> None:
    settings = parse_agent_settings({})

    assert settings == AgentSettings()


def test_parse_agent_settings_commands() -> None:
    settings = parse_agent_settings(
        {
            "interactive": False,
            "exit_commands": ["bye"],
            "stop_turn_commands": "halt,cancel",
        }
    )

    assert settings.interactive is False
    assert settings.input_commands.exit_commands == ("bye",)
    assert settings.input_commands.stop_turn_commands == ("halt", "cancel")


def test_parse_agent_settings_rejects_empty_commands() -> None:
    with pytest.raises(ConfigError):
        parse_agent_settings({"exit_commands": []})


def test_parse_agent_settings_rejects_reflection_schedule() -> None:
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_agent_settings({"scheduler": {"enabled": False}})


def test_parse_agent_settings_uses_program_outcome_retention_name() -> None:
    settings = parse_agent_settings({"retained_outcomes": 7})

    assert settings.retained_outcomes == 7
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_agent_settings({"retained_turn_outcomes": 7})
