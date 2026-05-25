"""Unit tests for LLM provider adapters — parameter building."""

from __future__ import annotations

import pytest

from tinysoul.llm.provider.adapters.base import OpenAIChatAdapter
from tinysoul.llm.provider.config import ChatConfig, ModelConfig
from tinysoul.llm.provider.request import AIRequest


class TestOpenAIChatAdapterBuildParams:
    """Verify _build_params constructs correct kwargs for the OpenAI SDK."""

    def test_timeout_from_model_config(self):
        adapter = OpenAIChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="test", model="m", timeout=30.0)
        params = adapter._build_params(request, config)
        assert params["timeout"] == 30.0

    def test_request_config_not_inspected_by_adapter(self):
        """Adapter receives already-merged config; request.config is not read."""
        adapter = OpenAIChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(
            messages=[{"role": "user", "content": "hi"}],
            config=ChatConfig(timeout=15.0),
        )
        # Adapter does NOT read request.config — it relies on _call_with_retry
        # to have already merged request.config into the passed config.
        config = ModelConfig(provider="test", model="m", timeout=30.0)
        params = adapter._build_params(request, config)
        assert params["timeout"] == 30.0

    def test_no_timeout_when_none(self):
        adapter = OpenAIChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="test", model="m", timeout=None)
        params = adapter._build_params(request, config)
        assert "timeout" not in params

    def test_basic_params_always_present(self):
        adapter = OpenAIChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="test", model="m")
        params = adapter._build_params(request, config)
        assert params["model"] == "m"
        assert params["messages"] == request.messages
        assert params["stream"] is False

    def test_system_messages_are_sent_before_user_messages(self):
        adapter = OpenAIChatAdapter(api_key="fake", base_url="http://fake")
        system = [{"role": "system", "content": "You are precise."}]
        messages = [{"role": "user", "content": "hi"}]
        request = AIRequest(messages=messages, system=system)
        config = ModelConfig(provider="test", model="m")
        params = adapter._build_params(request, config)
        assert params["messages"] == system + messages
