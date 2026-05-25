"""Zhipu AI (GLM) adapters."""

from __future__ import annotations

from typing import Any

from .base import OpenAIChatAdapter, OpenAIEmbeddingAdapter, OpenAIImageGenAdapter, register_adapter
from ..config import ModelConfig


@register_adapter("zhipu", "chat")
class ZhipuChatAdapter(OpenAIChatAdapter):
    """Zhipu AI (GLM) via OpenAI-compatible API."""

    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
    ENV_KEY_NAMES = ("GLM_API_KEY", "ZHIPU_API_KEY")

    def _build_params(self, request: Any, config: ModelConfig) -> dict[str, Any]:
        params = super()._build_params(request, config)
        if config.enable_thinking:
            params.setdefault("extra_body", {})
            params["extra_body"]["thinking"] = {"type": "enabled"}
        return params


@register_adapter("zhipu", "embedding")
class ZhipuEmbeddingAdapter(OpenAIEmbeddingAdapter):
    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
    ENV_KEY_NAMES = ("GLM_API_KEY", "ZHIPU_API_KEY")


@register_adapter("zhipu", "image_gen")
class ZhipuImageGenAdapter(OpenAIImageGenAdapter):
    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
    ENV_KEY_NAMES = ("GLM_API_KEY", "ZHIPU_API_KEY")
