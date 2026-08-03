from __future__ import annotations

import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.loop import LoopSettings, TurnSettings, parse_loop_settings


def test_loop_config_has_independent_user_and_maintenance_turn_budgets() -> None:
    settings = parse_loop_settings(
        {
            "user": {"max_cycles": 12},
            "maintenance": {"max_cycles": 30},
            "phase_retry_limit": 3,
        }
    )

    assert settings.user == TurnSettings(max_cycles=12)
    assert settings.maintenance == TurnSettings(max_cycles=30)
    assert settings.phase_retry_limit == 3


def test_loop_config_defaults() -> None:
    assert parse_loop_settings({}) == LoopSettings()


def test_loop_config_rejects_daily_and_invalid_turn_budget() -> None:
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_loop_settings({"daily": {}})
    with pytest.raises(ConfigError, match="positive"):
        TurnSettings(max_cycles=0)
