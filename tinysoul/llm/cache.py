"""Prompt cache intent model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptCache:
    """A request-level prompt caching intent."""

    key: str
