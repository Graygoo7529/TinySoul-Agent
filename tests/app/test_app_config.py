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
