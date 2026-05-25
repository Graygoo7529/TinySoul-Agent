"""AI module for TinySoul.

Provides unified interface for Chat, Embedding, and Image Generation.
"""

from .client import AIClient, get_ai_client, reset_ai_client
from .config import (
    ChatConfig,
    ChatModelOverride,
    ChatProfile,
    EmbedConfig,
    ImageConfig,
    LLMProfileName,
    ModelCapability,
    ModelConfig,
    ModelType,
)
from .request import AIRequest
from .resolver import merge_config, resolve_defaults
from .response import AIResponse

__all__ = [
    # client
    "AIClient",
    "get_ai_client",
    "reset_ai_client",
    # config
    "ModelConfig",
    "ChatConfig",
    "ChatModelOverride",
    "ChatProfile",
    "EmbedConfig",
    "ImageConfig",
    "LLMProfileName",
    "ModelType",
    "ModelCapability",
    # request / response
    "AIRequest",
    "AIResponse",
    # resolver
    "merge_config",
    "resolve_defaults",
]
