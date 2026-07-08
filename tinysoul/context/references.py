"""Prompt reference protocol shared by task prompt builders."""

from __future__ import annotations

from typing import Protocol

from tinysoul.infra.json import JsonObject

from .prompts import PromptBlock


class PromptReferenceError(Exception):
    """Raised when a task prompt reference cannot be resolved."""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "prompt_reference_error",
        payload: JsonObject | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.payload = payload or {}


class PromptReferenceResolver(Protocol):
    """Resolve structured task prompt references into prompt blocks."""

    def supports(self, kind: str) -> bool:
        """Return whether this resolver handles a reference kind."""
        ...

    def resolve(self, reference: JsonObject) -> tuple[PromptBlock, ...]:
        """Resolve one structured reference into prompt blocks."""
        ...
