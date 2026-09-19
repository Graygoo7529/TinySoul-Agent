"""LLM reasoning trace model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.infra.json import JsonObject


class ReasoningKeep(StrEnum):
    """How TinySoul should preserve assistant reasoning for a model."""

    NONE = "none"
    CONTENT = "content"
    ENCRYPTED = "encrypted"


@dataclass(frozen=True)
class Reasoning:
    """Provider-neutral reasoning associated with an assistant message."""

    content: str | None = None
    summary: str | None = None
    encrypted_items: tuple[JsonObject, ...] = ()

    @classmethod
    def text(cls, content: str) -> "Reasoning":
        return cls(content=content)
