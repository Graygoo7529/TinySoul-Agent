"""Prompt cache intent model."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LLMContractError


@dataclass(frozen=True)
class PromptCache:
    """Provider-neutral prompt cache intent.

    The key identifies a stable prompt prefix for providers that support
    cache routing or cache retention hints.
    """

    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise LLMContractError("PromptCache.key must be non-empty")
