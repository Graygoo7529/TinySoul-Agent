"""Moonshot AI / Kimi adapters."""

from __future__ import annotations

from typing import Any

from .base import OpenAIChatAdapter, OpenAIEmbeddingAdapter, OpenAIImageGenAdapter, register_adapter
from ..config import ModelConfig


@register_adapter("kimi", "chat")
class KimiChatAdapter(OpenAIChatAdapter):
    """Moonshot AI / Kimi via OpenAI-compatible API."""

    DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
    ENV_KEY_NAMES = ("KIMI_API_KEY", "MOONSHOT_API_KEY")

    def _build_params(self, request: Any, config: ModelConfig) -> dict[str, Any]:
        params = super()._build_params(request, config)
        if "max_tokens" in params:
            params["max_completion_tokens"] = params.pop("max_tokens")
        if config.model.startswith(("kimi-k2.6", "kimi-k2.5")):
            # Kimi-specific "thinking" param must go through extra_body so the
            # OpenAI SDK does not reject it as an unknown top-level argument.
            params.setdefault("extra_body", {})
            params["extra_body"]["thinking"] = {
                "type": "enabled" if config.enable_thinking else "disabled"
            }
            # Kimi k2.6 only allows temperature=0.6; remove the key so the API
            # uses its internal default rather than rejecting the request.
            params.pop("temperature", None)
        return params


@register_adapter("kimi", "embedding")
class KimiEmbeddingAdapter(OpenAIEmbeddingAdapter):
    DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
    ENV_KEY_NAMES = ("KIMI_API_KEY", "MOONSHOT_API_KEY")


@register_adapter("kimi", "image_gen")
class KimiImageGenAdapter(OpenAIImageGenAdapter):
    DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
    ENV_KEY_NAMES = ("KIMI_API_KEY", "MOONSHOT_API_KEY")
