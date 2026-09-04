"""Stable adapter identity types."""

from enum import StrEnum


class AdapterKind(StrEnum):
    """Provider/model behavior implementation independent of endpoint identity."""

    OPENAI_COMPATIBLE_CHAT = "openai_compatible_chat"
    OPENAI = "openai"
    KIMI = "kimi"
    DEEPSEEK = "deepseek"
    GLM = "glm"
    MINIMAX = "minimax"


class ProviderApiStyle(StrEnum):
    """Wire protocol shape required by a provider adapter."""

    OPENAI_CHAT = "openai_chat"
    OPENAI_RESPONSES = "openai_responses"
