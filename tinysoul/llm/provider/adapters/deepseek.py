"""DeepSeek adapters."""

from __future__ import annotations

from typing import Any

from .base import OpenAIChatAdapter, OpenAIEmbeddingAdapter, register_adapter
from ..config import ModelConfig


@register_adapter("deepseek", "chat")
class DeepSeekChatAdapter(OpenAIChatAdapter):
    """DeepSeek via OpenAI-compatible API."""

    DEFAULT_BASE_URL = "https://api.deepseek.com"
    ENV_KEY_NAMES = ("DEEPSEEK_API_KEY",)

    def _build_params(self, request: Any, config: ModelConfig) -> dict[str, Any]:
        params = super()._build_params(request, config)
        if config.enable_thinking:
            params["thinking"] = {"type": "enabled"}
            params["reasoning_effort"] = "high"
        return params


@register_adapter("deepseek", "embedding")
class DeepSeekEmbeddingAdapter(OpenAIEmbeddingAdapter):
    DEFAULT_BASE_URL = "https://api.deepseek.com"
    ENV_KEY_NAMES = ("DEEPSEEK_API_KEY",)
