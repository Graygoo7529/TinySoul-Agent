"""LLM provider adapters for TinySoul.

Provides chat, embedding, and image generation adapters for multiple providers.
"""

from .base import (
    _ADAPTER_REGISTRY,
    ChatAdapter,
    create_adapter,
    EmbeddingAdapter,
    ImageGenAdapter,
    OpenAIChatAdapter,
    OpenAIEmbeddingAdapter,
    OpenAIImageGenAdapter,
    register_adapter,
)

# Import provider modules to trigger adapter registration
from . import zhipu, kimi, deepseek, minimax

# Re-export concrete adapter classes for convenience
from .zhipu import ZhipuChatAdapter, ZhipuEmbeddingAdapter, ZhipuImageGenAdapter
from .kimi import KimiChatAdapter, KimiEmbeddingAdapter, KimiImageGenAdapter
from .deepseek import DeepSeekChatAdapter, DeepSeekEmbeddingAdapter
from .minimax import MiniMaxChatAdapter, MiniMaxEmbeddingAdapter

__all__ = [
    "_ADAPTER_REGISTRY",
    "ChatAdapter",
    "EmbeddingAdapter",
    "ImageGenAdapter",
    "OpenAIChatAdapter",
    "OpenAIEmbeddingAdapter",
    "OpenAIImageGenAdapter",
    "register_adapter",
    "create_adapter",
    "ZhipuChatAdapter",
    "ZhipuEmbeddingAdapter",
    "ZhipuImageGenAdapter",
    "KimiChatAdapter",
    "KimiEmbeddingAdapter",
    "KimiImageGenAdapter",
    "DeepSeekChatAdapter",
    "DeepSeekEmbeddingAdapter",
    "MiniMaxChatAdapter",
    "MiniMaxEmbeddingAdapter",
]
