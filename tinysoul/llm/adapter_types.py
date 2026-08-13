"""Stable adapter identity types."""

from enum import StrEnum


class AdapterKind(StrEnum):
    """Provider/model behavior implementation independent of endpoint identity."""

    GENERIC = "generic"
    OPENAI = "openai"
    KIMI = "kimi"
    DEEPSEEK = "deepseek"
    GLM = "glm"
    MINIMAX = "minimax"

