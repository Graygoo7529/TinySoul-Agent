from __future__ import annotations

import pytest

from tinysoul.agent.config import AgentSettings
from tinysoul.agent.config import parse_agent_settings
from tinysoul.infra.config import ConfigError


def test_parse_agent_settings_defaults() -> None:
    settings = parse_agent_settings({})

    assert settings == AgentSettings()


def test_parse_agent_settings_rejects_invalid_retention() -> None:
    with pytest.raises(ConfigError):
        parse_agent_settings({"retained_outcomes": 0})


def test_parse_agent_settings_rejects_reflection_schedule() -> None:
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_agent_settings({"scheduler": {"enabled": False}})


def test_parse_agent_settings_retains_completed_outcomes() -> None:
    settings = parse_agent_settings({"retained_outcomes": 7})

    assert settings.retained_outcomes == 7
