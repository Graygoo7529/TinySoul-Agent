"""Real API integration tests for Kimi (Moonshot AI)."""

from __future__ import annotations

import os

import pytest

from tinysoul.llm.provider.adapters import KimiChatAdapter, create_adapter
from tinysoul.llm.provider.client import AIClient
from tinysoul.llm.provider.config import LLMProfileName, ModelConfig, ModelType
from tinysoul.llm.provider.request import AIRequest

_RUN_REAL_API_TESTS = os.environ.get("RUN_REAL_API_TESTS", "").lower() in ("1", "true", "yes")


def _has_kimi_key() -> bool:
    return bool(os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY"))


@pytest.mark.skipif(not _RUN_REAL_API_TESTS, reason="Set RUN_REAL_API_TESTS=1")
@pytest.mark.real_api
class TestKimiProvider:
    def test_kimi_api_key_exists(self):
        assert _has_kimi_key(), "KIMI_API_KEY or MOONSHOT_API_KEY must be set"

    def test_adapter_direct_chat(self):
        api_key = os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
        adapter = KimiChatAdapter(api_key=api_key)
        config = ModelConfig(
            provider="kimi",
            model="kimi-k2.6",
            model_type=ModelType.CHAT,
            api_key=api_key,
            max_tokens=100,
            temperature=0.3,
        )
        request = AIRequest(messages=[{"role": "user", "content": "请回复一个汉字：好"}])
        response = adapter.chat(request, config)
        assert response.content
        assert "好" in response.content or len(response.content.strip()) > 0

    def test_via_aiclient(self):
        api_key = os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
        client = AIClient(
            configs=[
                ModelConfig(
                    provider="kimi",
                    model="kimi-k2.6",
                    model_type=ModelType.CHAT,
                    api_key=api_key,
                    max_tokens=100,
                )
            ]
        )
        assert client.current_chat_model_name(LLMProfileName.STEP1) == "kimi-k2.6"
        response = client.chat(
            messages=[{"role": "user", "content": "Reply with one word: hello"}],
            profile=LLMProfileName.STEP1,
        )
        assert response.content


@pytest.mark.skipif(not _has_kimi_key(), reason="KIMI_API_KEY not set")
def test_adapter_factory_resolution():
    api_key = os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
    config = ModelConfig(provider="kimi", model="kimi-k2.6", model_type=ModelType.CHAT, api_key=api_key)
    adapter = create_adapter(config)
    assert isinstance(adapter, KimiChatAdapter)
