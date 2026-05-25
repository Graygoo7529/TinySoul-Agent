"""Test that ActionRegistry bootstrap works without API keys."""

import pytest

from tinysoul.action.framework.registry import ActionRegistry
from tinysoul.action.handlers import bootstrap
from tests.helpers.factories import run_config
from tests.helpers.fakes import FakeContextProvider


class TestBootstrapWithoutApiKey:
    def test_bootstrap_succeeds_without_api_key(self, monkeypatch):
        """bootstrap() should not fail when no LLM API keys are set."""
        # Clear all known API key env vars
        for key in [
            "GLM_API_KEY", "ZHIPU_API_KEY", "KIMI_API_KEY", "MOONSHOT_API_KEY",
            "DEEPSEEK_API_KEY", "MINIMAX_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        registry = bootstrap()

        # Non-LLM actions should still be available
        available = registry.get_available_action_names()
        assert "calculate" in available
        assert "answer" in available
        assert "reasoning" in available

    def test_calculate_can_execute_without_api_key(self, monkeypatch):
        """calculate action should work even when no LLM keys are present."""
        for key in [
            "GLM_API_KEY", "ZHIPU_API_KEY", "KIMI_API_KEY", "MOONSHOT_API_KEY",
            "DEEPSEEK_API_KEY", "MINIMAX_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        registry = bootstrap()
        handler = registry.get_handler("calculate")

        result = handler.execute(
            {"expression": "3 + 4"},
            FakeContextProvider(),
            run_config("calculate"),
        )
        assert result["value"] == 7
