from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.kernel.loop import TurnSettings
from tinysoul.plugins.reflection import (ReflectionSettings, parse_maintenance_settings)


def test_maintenance_owns_its_turn_budget(tmp_path: Path) -> None:
    settings = parse_maintenance_settings(
        {"home": {"max_cycles": 31}},
        project_root=tmp_path,
    )

    assert settings.home == TurnSettings(max_cycles=31)


def test_maintenance_turn_budget_defaults_and_rejects_old_loop_shape(
    tmp_path: Path,
) -> None:
    assert parse_maintenance_settings({}, project_root=tmp_path).home == TurnSettings()
    with pytest.raises(ConfigError, match="Unknown configuration key"):
        parse_maintenance_settings(
            {"maintenance": {"max_cycles": 31}},
            project_root=tmp_path,
        )


def test_maintenance_settings_require_typed_turn_settings(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="scenario settings"):
        ReflectionSettings(
            archive_root=tmp_path / "archive",
            runtime_root=tmp_path / "runtime",
            home=cast(TurnSettings, object()),
        )
