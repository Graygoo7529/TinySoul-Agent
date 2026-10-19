"""Stable API mode and adapter identity types."""

from enum import StrEnum


class ApiMode(StrEnum):
    """Supported external model API contracts."""

    OPENAI_CHAT = "openai-chat"
    OPENAI_RESPONSES = "openai-responses"
    ANTHROPIC_MESSAGES = "anthropic-messages"
    GOOGLE_GENERATE_CONTENT = "google-generate-content"


class AdapterKind(StrEnum):
    """Stable model adapter identity."""

    OPENAI_CHAT = "openai-chat"
    OPENAI_RESPONSES = "openai-responses"
    GPT = "gpt"
    KIMI = "kimi"
    DEEPSEEK = "deepseek"
    GLM = "glm"
    MINIMAX = "minimax"
    ANTHROPIC_MESSAGES = "anthropic-messages"
    GOOGLE_GENERATE_CONTENT = "google-generate-content"
