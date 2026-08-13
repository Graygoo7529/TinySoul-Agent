from __future__ import annotations

import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.loop import (
    CycleSettings,
    LoopSettings,
    TurnSettings,
    parse_loop_settings,
    validate_cycle_task_profiles,
)


def test_loop_config_owns_user_turn_budget() -> None:
    settings = parse_loop_settings(
        {
            "user": {"max_cycles": 12},
        }
    )

    assert settings.user == TurnSettings(max_cycles=12)


def test_loop_config_owns_shared_cycle_task_profiles() -> None:
    settings = parse_loop_settings(
        {
            "cycle": {
                "phase1_task_profile": "cycle_planner",
                "phase2_task_profile": "cycle_executor",
            },
        }
    )

    assert settings.cycle == CycleSettings(
        phase1_task_profile="cycle_planner",
        phase2_task_profile="cycle_executor",
    )


def test_loop_config_validates_shared_cycle_task_profiles() -> None:
    with pytest.raises(ConfigError, match="unknown task profile"):
        validate_cycle_task_profiles(
            CycleSettings(
                phase1_task_profile="cycle_planner",
                phase2_task_profile="cycle_executor",
            ),
            task_profiles=("cycle_planner",),
        )


def test_loop_config_rejects_removed_phase_retry_limit() -> None:
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_loop_settings({"phase_retry_limit": 3})


def test_loop_config_defaults() -> None:
    assert parse_loop_settings({}) == LoopSettings()


def test_loop_config_rejects_daily_and_invalid_turn_budget() -> None:
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_loop_settings({"daily": {}})
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_loop_settings({"maintenance": {}})
    with pytest.raises(ConfigError, match="positive"):
        TurnSettings(max_cycles=0)
