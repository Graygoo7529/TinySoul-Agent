"""Real API integration tests for GLM (Zhipu AI)."""

from __future__ import annotations

import os

import pytest

from tinysoul.llm.provider import get_ai_client, reset_ai_client
from tinysoul.llm.provider.config import LLMProfileName

_RUN_REAL_API_TESTS = os.environ.get("RUN_REAL_API_TESTS", "").lower() in ("1", "true", "yes")


@pytest.fixture
def glm_client():
    reset_ai_client()
    return get_ai_client()


@pytest.mark.skipif(not _RUN_REAL_API_TESTS, reason="Set RUN_REAL_API_TESTS=1")
@pytest.mark.real_api
class TestGLMProvider:
    def test_chat_with_system_message(self, glm_client):
        system_msg = [{"role": "system", "content": "你是一个乐于助人的AI助手，回答要简洁明了。"}]
        messages = [{"role": "user", "content": "什么是Python？"}]
        response = glm_client.chat(
            messages=messages,
            profile=LLMProfileName.STEP1,
            system=system_msg,
        )
        assert response.content is not None
        assert len(response.content) > 0
        assert "Python" in response.content

    def test_chat_user_prompt_only(self, glm_client):
        messages = [{"role": "user", "content": "你好，请用10个字介绍自己。"}]
        response = glm_client.chat(messages=messages, profile=LLMProfileName.STEP1)
        assert response.content is not None
        assert len(response.content) > 0
