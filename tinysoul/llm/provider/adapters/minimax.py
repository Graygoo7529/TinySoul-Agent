"""MiniMax adapters."""

from __future__ import annotations

import re
from typing import Any

from .base import OpenAIChatAdapter, OpenAIEmbeddingAdapter, register_adapter
from ..config import ModelConfig


@register_adapter("minimax", "chat")
class MiniMaxChatAdapter(OpenAIChatAdapter):
    """MiniMax via OpenAI-compatible API."""

    DEFAULT_BASE_URL = "https://api.minimaxi.com"
    ENV_KEY_NAMES = ("MINIMAX_API_KEY",)

    def _build_params(self, request: Any, config: ModelConfig) -> dict[str, Any]:
        params = super()._build_params(request, config)
        if "max_tokens" in params:
            params["max_completion_tokens"] = min(params.pop("max_tokens"), 2048)
        return params

    def _extract_content(self, response: Any) -> tuple[str, str | None]:
        content, reasoning = super()._extract_content(response)
        content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
        return content, reasoning


@register_adapter("minimax", "embedding")
class MiniMaxEmbeddingAdapter(OpenAIEmbeddingAdapter):
    DEFAULT_BASE_URL = "https://api.minimaxi.com"
    ENV_KEY_NAMES = ("MINIMAX_API_KEY",)
