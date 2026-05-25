"""AI request representation for TinySoul.

Canonical intermediate representation between tasks and the client layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import ChatConfig


@dataclass
class AIRequest:
    """A chat completion request carrying messages, system context, and optional
    per-request generation overrides.

    The ``config`` field carries generation parameters (temperature, max_tokens,
    etc.) that override the pool-level ModelConfig for this single request.
    It cannot carry identity fields (provider, model, api_key) — those are
    managed by the client pool failover system.
    """

    messages: list[dict[str, Any]]
    system: list[dict[str, str]] | None = None
    config: ChatConfig | None = None
