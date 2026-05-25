"""LLM module for TinySoul.

Provides unified interface for LLM providers and AI task execution.
"""

from .provider import (
    AIClient,
    AIRequest,
    AIResponse,
    ChatConfig,
    ChatModelOverride,
    ChatProfile,
    EmbedConfig,
    ImageConfig,
    LLMProfileName,
    ModelCapability,
    ModelConfig,
    ModelType,
    get_ai_client,
    reset_ai_client,
)
from .tasks import AITask, Attachment, ContentBuilder, Example, InputSpec, LLMPrompt, OutputConstraint, PromptBuilder, TaskResult

__all__ = [
    # provider
    "AIClient",
    "AIRequest",
    "AIResponse",
    "ModelConfig",
    "ChatConfig",
    "ChatModelOverride",
    "ChatProfile",
    "EmbedConfig",
    "ImageConfig",
    "LLMProfileName",
    "ModelType",
    "ModelCapability",
    "get_ai_client",
    "reset_ai_client",
    # tasks
    "AITask",
    "LLMPrompt",
    "InputSpec",
    "OutputConstraint",
    "Example",
    "PromptBuilder",
    "Attachment",
    "ContentBuilder",
    "TaskResult",
]
