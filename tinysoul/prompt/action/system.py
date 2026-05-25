"""LLM action system message assembly."""

from __future__ import annotations

from typing import Any

from .resources import get_action_execution_context


def build_llm_action_system(
    context_provider: Any,
    action_system: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build the complete system message stack for an internal LLM action.

    Ordering is intentional:
    1. loop-level system messages
    2. generic action execution context
    3. action-specific system messages
    """

    loop_system: list[dict[str, str]] = []
    getter = getattr(context_provider, "get_loop_level_system", None)
    if callable(getter):
        resolved = getter()
        if resolved is not None:
            loop_system = list(resolved)

    return [
        *loop_system,
        {"role": "system", "content": get_action_execution_context()},
        *(list(action_system) if action_system else []),
    ]


__all__ = ["build_llm_action_system"]
