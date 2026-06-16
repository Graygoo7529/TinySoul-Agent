"""Prompt cache intent model."""

from __future__ import annotations

from dataclasses import dataclass, field

from .messages import MessageScope


@dataclass(frozen=True)
class PromptCache:
    """A request-level prompt caching intent."""

    key: str
    scopes: tuple[MessageScope, ...] = field(default_factory=tuple)

