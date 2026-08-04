from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.loop import TurnSettings
from tinysoul.maintenance import MaintenanceSettings, parse_maintenance_settings


def test_maintenance_owns_its_turn_budget(tmp_path: Path) -> None:
    settings = parse_maintenance_settings(
        {"turn": {"max_cycles": 31}},
        project_root=tmp_path,
    )

    assert settings.turn == TurnSettings(max_cycles=31)


def test_maintenance_turn_budget_defaults_and_rejects_old_loop_shape(
    tmp_path: Path,
) -> None:
    assert parse_maintenance_settings({}, project_root=tmp_path).turn == TurnSettings()
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_maintenance_settings(
            {"maintenance": {"max_cycles": 31}},
            project_root=tmp_path,
        )


def test_maintenance_settings_require_typed_turn_settings(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="turn settings"):
        MaintenanceSettings(
            archive_root=tmp_path / "archive",
            runtime_root=tmp_path / "runtime",
            turn=cast(TurnSettings, object()),
        )
