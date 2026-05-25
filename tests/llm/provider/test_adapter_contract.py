"""Adapter contract tests — validate parameter building without real API calls."""

from __future__ import annotations

import pytest

from tinysoul.llm.provider.adapters.base import OpenAIChatAdapter
from tinysoul.llm.provider.adapters.kimi import KimiChatAdapter
from tinysoul.llm.provider.adapters.minimax import MiniMaxChatAdapter
from tinysoul.llm.provider.config import ChatConfig, ModelConfig
from tinysoul.llm.provider.request import AIRequest
from tinysoul.llm.provider.resolver import merge_config, resolve_defaults
from tinysoul.trap import ConfigError


class TestConfigResolver:
    """Unit tests for merge_config and resolve_defaults."""

    def test_merge_overrides_non_none_fields(self):
        base = ModelConfig(provider="p", model="m", temperature=0.7, max_tokens=4000)
        override = ChatConfig(temperature=0.3, max_tokens=2000)
        result = merge_config(base, override)
        assert result.temperature == 0.3
        assert result.max_tokens == 2000
        assert result.provider == "p"
        assert result.model == "m"

    def test_merge_preserves_base_when_override_is_none(self):
        base = ModelConfig(provider="p", model="m", temperature=0.7)
        override = ChatConfig(temperature=None)
        result = merge_config(base, override)
        assert result.temperature == 0.7

    def test_merge_none_override_returns_base_unchanged(self):
        base = ModelConfig(provider="p", model="m", temperature=0.7)
        result = merge_config(base, None)
        assert result.temperature == 0.7

    def test_resolve_defaults_fills_none_fields(self):
        config = ModelConfig(provider="p", model="m")
        result = resolve_defaults(config)
        assert result.temperature == 0.7
        assert result.max_tokens == 8000
        assert result.max_retries == 3
        assert result.base_retry_delay == 1.0
        assert result.timeout == 120.0
        assert result.enable_thinking is False

    def test_resolve_defaults_preserves_explicit_values(self):
        config = ModelConfig(provider="p", model="m", temperature=0.3, max_tokens=100)
        result = resolve_defaults(config)
        assert result.temperature == 0.3
        assert result.max_tokens == 100

    def test_merge_then_resolve(self):
        base = ModelConfig(provider="p", model="m", temperature=0.7)
        override = ChatConfig(temperature=0.3)
        merged = merge_config(base, override)
        result = resolve_defaults(merged)
        assert result.temperature == 0.3
        assert result.max_tokens == 8000  # filled by resolve_defaults


class TestOpenAIChatAdapterContract:
    """Validate OpenAIChatAdapter._build_params output structure."""

    def test_build_params_with_resolved_config(self):
        adapter = OpenAIChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(
            provider="test",
            model="gpt-4",
            temperature=0.5,
            max_tokens=100,
            timeout=30.0,
        )
        params = adapter._build_params(request, config)
        assert params["model"] == "gpt-4"
        assert params["temperature"] == 0.5
        assert params["max_tokens"] == 100
        assert params["timeout"] == 30.0
        assert params["messages"] == request.messages
        assert params["stream"] is False

    def test_build_params_preserves_system_message_order(self):
        adapter = OpenAIChatAdapter(api_key="fake", base_url="http://fake")
        system = [{"role": "system", "content": "Follow system policy."}]
        messages = [{"role": "user", "content": "hi"}]
        request = AIRequest(messages=messages, system=system)
        config = ModelConfig(provider="test", model="gpt-4")
        params = adapter._build_params(request, config)
        assert params["messages"] == system + messages

    def test_omits_fields_when_none(self):
        adapter = OpenAIChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="test", model="gpt-4", temperature=None, max_tokens=None, timeout=None)
        params = adapter._build_params(request, config)
        assert "temperature" not in params
        assert "max_tokens" not in params
        assert "timeout" not in params

    def test_extra_params_merged(self):
        adapter = OpenAIChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="test", model="gpt-4", extra_params={"top_p": 0.9})
        params = adapter._build_params(request, config)
        assert params["top_p"] == 0.9


class TestKimiChatAdapterContract:
    """Validate Kimi-specific parameter transformations."""

    def test_renames_max_tokens(self):
        adapter = KimiChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="kimi", model="kimi-k2.6", max_tokens=100)
        params = adapter._build_params(request, config)
        assert "max_tokens" not in params
        assert params["max_completion_tokens"] == 100

    def test_removes_temperature_for_k2_6(self):
        adapter = KimiChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="kimi", model="kimi-k2.6", temperature=0.7)
        params = adapter._build_params(request, config)
        assert "temperature" not in params

    def test_keeps_temperature_for_other_models(self):
        adapter = KimiChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="kimi", model="kimi-lite", temperature=0.7)
        params = adapter._build_params(request, config)
        assert params["temperature"] == 0.7

    def test_injects_thinking_via_extra_body(self):
        adapter = KimiChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="kimi", model="kimi-k2.6", enable_thinking=True)
        params = adapter._build_params(request, config)
        assert params["extra_body"]["thinking"]["type"] == "enabled"

    def test_thinking_disabled(self):
        adapter = KimiChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="kimi", model="kimi-k2.6", enable_thinking=False)
        params = adapter._build_params(request, config)
        assert params["extra_body"]["thinking"]["type"] == "disabled"


class TestMiniMaxChatAdapterContract:
    """Validate MiniMax-specific parameter transformations."""

    def test_caps_max_completion_tokens_at_2048(self):
        adapter = MiniMaxChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="minimax", model="MiniMax-M2.7", max_tokens=5000)
        params = adapter._build_params(request, config)
        assert "max_tokens" not in params
        assert params["max_completion_tokens"] == 2048

    def test_preserves_max_tokens_below_cap(self):
        adapter = MiniMaxChatAdapter(api_key="fake", base_url="http://fake")
        request = AIRequest(messages=[{"role": "user", "content": "hi"}])
        config = ModelConfig(provider="minimax", model="MiniMax-M2.7", max_tokens=1000)
        params = adapter._build_params(request, config)
        assert params["max_completion_tokens"] == 1000
