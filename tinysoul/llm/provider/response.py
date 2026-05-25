"""Unified AI response structure for TinySoul.

AIResponse is the single intermediate representation returned by every
adapter (chat, embedding, image_gen). Callers consume the relevant fields
and pass it to Interpreter for JSON extraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AIResponse:
    """Unified response from any AI model call.

    Fields are populated according to the call type:
    - chat:        content (+ optional reasoning_content)
    - embedding:   embedding vector
    - image_gen:   base64-encoded image strings

    metadata carries provider-specific data (token usage, finish_reason, etc.)
    """

    content: str = ""                         # Primary text output
    reasoning_content: str | None = None      # Chain-of-thought / thinking
    embedding: list[float] | None = None      # Embedding vector result
    images: list[str] | None = None           # Base64 image data
    metadata: dict = field(default_factory=dict)  # usage, model, finish_reason...
