from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tinysoul.infra.config import ConfigError
from tinysoul.loop import DailySettings, LoopSettings, parse_loop_settings


def test_loop_daily_config_resolves_iana_timezone_and_archive_root(
    tmp_path: Path,
) -> None:
    settings = parse_loop_settings(
        {
            "daily": {
                "timezone": "UTC",
                "archive_root": "history",
            }
        },
        project_root=tmp_path,
    )

    assert settings.daily.timezone == "UTC"
    assert settings.daily.archive_root == tmp_path / "history"


def test_loop_daily_config_defaults_to_shanghai_and_top_level_archive(
    tmp_path: Path,
) -> None:
    settings = parse_loop_settings({}, project_root=tmp_path)

    assert settings.daily.timezone == "Asia/Shanghai"
    assert settings.daily.archive_root == tmp_path / "archive"


def test_loop_daily_config_rejects_unknown_timezone_and_key() -> None:
    with pytest.raises(ConfigError) as timezone_error:
        DailySettings(timezone="Not/A_Timezone")
    assert timezone_error.value.key == "loop.daily.timezone"

    with pytest.raises(ConfigError) as key_error:
        parse_loop_settings({"daily": {"unknown": True}})
    assert key_error.value.key == "loop.daily.unknown"


def test_loop_settings_direct_construction_rejects_invalid_daily_type() -> None:
    with pytest.raises(ConfigError, match="DailySettings"):
        LoopSettings(daily=cast(DailySettings, True))
