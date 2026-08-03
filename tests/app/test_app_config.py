from __future__ import annotations

import pytest

from tinysoul.app import AppSettings, parse_app_settings
from tinysoul.infra.config import ConfigError


def test_parse_app_settings_defaults() -> None:
    settings = parse_app_settings({})

    assert settings == AppSettings()


def test_parse_app_settings_commands() -> None:
    settings = parse_app_settings(
        {
            "interactive": False,
            "exit_commands": ["bye"],
            "stop_turn_commands": "halt,cancel",
        }
    )

    assert settings.interactive is False
    assert settings.input_commands.exit_commands == ("bye",)
    assert settings.input_commands.stop_turn_commands == ("halt", "cancel")


def test_parse_app_settings_rejects_empty_commands() -> None:
    with pytest.raises(ConfigError):
        parse_app_settings({"exit_commands": []})


def test_parse_app_settings_rejects_maintenance_schedule() -> None:
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_app_settings({"scheduler": {"enabled": False}})


def test_parse_app_settings_uses_program_outcome_retention_name() -> None:
    settings = parse_app_settings({"retained_outcomes": 7})

    assert settings.retained_outcomes == 7
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_app_settings({"retained_turn_outcomes": 7})
