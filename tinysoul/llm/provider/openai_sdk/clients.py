"""Client protocols for OpenAI SDK shaped provider adapters."""

from __future__ import annotations

from typing import Protocol


class OpenAIResponsesClient(Protocol):
    """Narrow SDK surface used by the Responses adapter."""

    def create(self, **kwargs: object) -> object:
        ...


class OpenAIChatCompletionsClient(Protocol):
    """Narrow SDK surface used by the Chat Completions adapter."""

    def create(self, **kwargs: object) -> object:
        ...


class ModelDumpable(Protocol):
    """Object that can expose a JSON-safe mapping."""

    def model_dump(self, *, mode: str) -> object:
        ...


__all__ = [
    "ModelDumpable",
    "OpenAIChatCompletionsClient",
    "OpenAIResponsesClient",
]
