"""Prompt cache intent model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptCache:
    """Provider-neutral prompt cache intent.

    The key identifies a stable prompt prefix for providers that support
    cache routing or cache retention hints.
    """

    key: str
