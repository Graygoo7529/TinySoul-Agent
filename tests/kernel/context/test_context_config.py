from __future__ import annotations

import pytest

from tinysoul.kernel.context.config import parse_context_settings
from tinysoul.infra.config import ConfigError


def test_context_pressure_ratio_defaults() -> None:
    settings = parse_context_settings({})

    assert settings.compression_trigger_ratio == pytest.approx(0.8)
    assert settings.compression_target_ratio == pytest.approx(0.5)
    assert settings.max_image_bytes is None
    assert settings.max_window_tokens is None


def test_context_accepts_window_limit() -> None:
    assert parse_context_settings({"max_window_tokens": 100}).max_window_tokens == 100


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "100"])
def test_context_rejects_invalid_window_limit(value: object) -> None:
    with pytest.raises(ConfigError) as raised:
        parse_context_settings({"max_window_tokens": value})
    assert raised.value.key == "context.max_window_tokens"


def test_context_rejects_target_at_or_above_trigger() -> None:
    with pytest.raises(ConfigError, match="below the trigger ratio"):
        parse_context_settings(
            {
                "compression_trigger_ratio": 0.8,
                "compression_target_ratio": 0.8,
            }
        )
