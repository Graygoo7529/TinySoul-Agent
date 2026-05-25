"""Unit tests for settings loading, .env parsing, and environment overrides."""

from __future__ import annotations

import os

import pytest

from tinysoul.infra.config.settings import (
    GlobalSettings,
    _convert_env_value,
    _env,
    _load_dotenv,
)
from tinysoul.llm.provider.config import ModelCapability, build_chat_profiles


class TestEnvHelper:
    def test_env_returns_none_for_missing(self):
        assert _env("TINYSOUL_THIS_SHOULD_NOT_EXIST_12345") is None

    def test_env_returns_none_for_empty(self, monkeypatch):
        monkeypatch.setenv("TINYSOUL_TEST_EMPTY", "")
        assert _env("TINYSOUL_TEST_EMPTY") is None

    def test_env_returns_value(self, monkeypatch):
        monkeypatch.setenv("TINYSOUL_TEST_VALUE", "hello")
        assert _env("TINYSOUL_TEST_VALUE") == "hello"


class TestConvertEnvValue:
    def test_int(self):
        assert _convert_env_value("42", int) == 42

    def test_float(self):
        assert _convert_env_value("3.14", float) == 3.14

    def test_bool_true_variants(self):
        for val in ("1", "true", "yes", "on", "TRUE", "Yes"):
            assert _convert_env_value(val, bool) is True

    def test_bool_false_variants(self):
        for val in ("0", "false", "no", "off", "FALSE", "No"):
            assert _convert_env_value(val, bool) is False

    def test_list_str(self):
        assert _convert_env_value("a,b,c", list[str]) == ["a", "b", "c"]

    def test_list_str_with_spaces(self):
        assert _convert_env_value("a, b, c", list[str]) == ["a", "b", "c"]

    def test_str_passthrough(self):
        assert _convert_env_value("hello", str) == "hello"


class TestLoadDotenv:
    def test_loads_key_value_pairs(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_TEST_VAR=from_dotenv\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("MY_TEST_VAR", raising=False)
        _load_dotenv()
        assert os.environ.get("MY_TEST_VAR") == "from_dotenv"

    def test_skips_comments_and_empty_lines(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nREAL_VAR=123\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("REAL_VAR", raising=False)
        _load_dotenv()
        assert os.environ.get("REAL_VAR") == "123"

    def test_does_not_override_existing_env(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("PRESERVED=from_file\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PRESERVED", "from_env")
        _load_dotenv()
        assert os.environ.get("PRESERVED") == "from_env"


class TestGlobalSettingsFromEnv:
    def test_defaults_when_no_env(self):
        settings = GlobalSettings()
        assert settings.max_turns == 20
        assert settings.temperature == 0.7
        assert settings.log_level == "normal"

    def test_override_int(self, monkeypatch):
        monkeypatch.setenv("TINYSOUL_MAX_TURNS", "50")
        settings = GlobalSettings.from_env()
        assert settings.max_turns == 50

    def test_override_float(self, monkeypatch):
        monkeypatch.setenv("TINYSOUL_TEMPERATURE", "0.3")
        settings = GlobalSettings.from_env()
        assert settings.temperature == pytest.approx(0.3)

    def test_override_bool(self, monkeypatch):
        monkeypatch.setenv("TINYSOUL_SOME_FLAG", "true")
        # GlobalSettings does not have a bool field by default; test via conversion
        assert _convert_env_value("true", bool) is True

    def test_override_dict(self, monkeypatch):
        monkeypatch.setenv(
            "TINYSOUL_CHAT_PROFILES",
            '{"step1": {"provider_chain": ["kimi"], "required_capabilities": ["text"], "chat_model_overrides": {}, "config": {}}, '
            '"step2": {"provider_chain": ["deepseek"], "required_capabilities": ["text"], "chat_model_overrides": {}, "config": {}}, '
            '"step3": {"provider_chain": ["zhipu"], "required_capabilities": ["text"], "chat_model_overrides": {"zhipu": {"model": "glm-test", "capabilities": ["text"]}}, "config": {}}, '
            '"action_llm": {"provider_chain": ["minimax"], "required_capabilities": ["text"], "preferred_capabilities": ["vision"], "chat_model_overrides": {}, "config": {}}}',
        )
        settings = GlobalSettings.from_env()
        assert settings.chat_profiles["step1"]["provider_chain"] == ["kimi"]
        assert settings.chat_profiles["step3"]["chat_model_overrides"]["zhipu"]["model"] == "glm-test"
        assert settings.chat_profiles["action_llm"]["provider_chain"] == ["minimax"]

        profiles = build_chat_profiles(settings.chat_profiles)
        override = profiles["step3"].chat_model_overrides["zhipu"]
        assert override.model == "glm-test"
        assert override.capabilities == [ModelCapability.TEXT]

    def test_override_str(self, monkeypatch):
        monkeypatch.setenv("TINYSOUL_LOG_LEVEL", "debug")
        settings = GlobalSettings.from_env()
        assert settings.log_level == "debug"

    def test_unknown_field_ignored(self, monkeypatch):
        # Setting an env var for a non-existent field should not crash
        monkeypatch.setenv("TINYSOUL_NONEXISTENT", "value")
        settings = GlobalSettings.from_env()
        assert hasattr(settings, "max_turns")
