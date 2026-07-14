from __future__ import annotations

from datetime import time as WallTime

import pytest

from tinysoul.app import AppSettings, SchedulerSettings, parse_app_settings
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


def test_parse_app_scheduler_settings() -> None:
    settings = parse_app_settings(
        {
            "scheduler": {
                "enabled": False,
                "home_maintenance_time": "01:05",
                "memory_maintenance_time": "01:15",
            }
        }
    )

    assert settings.scheduler == SchedulerSettings(
        enabled=False,
        home_maintenance_time=SchedulerSettings.home_maintenance_time.replace(
            hour=1
        ),
        memory_maintenance_time=SchedulerSettings.memory_maintenance_time.replace(
            hour=1
        ),
    )


def test_parse_app_scheduler_rejects_invalid_order_and_time_format() -> None:
    with pytest.raises(ConfigError, match="before Memory"):
        parse_app_settings(
            {
                "scheduler": {
                    "home_maintenance_time": "00:20",
                    "memory_maintenance_time": "00:15",
                }
            }
        )
    with pytest.raises(ConfigError, match="without seconds"):
        parse_app_settings(
            {"scheduler": {"home_maintenance_time": "00:05:01"}}
        )
    with pytest.raises(ConfigError, match="minute precision"):
        SchedulerSettings(home_maintenance_time=WallTime(0, 5, 1))
