"""Reflection Turn prompt guidance."""

from __future__ import annotations

from tinysoul.prompts.plugins import reflection as prompt_text

from ..errors import ReflectionContractError


def reflection_turn_guidance(kind: str) -> tuple[str, ...]:
    common = prompt_text.COMMON_GUIDANCE
    if kind == "home":
        return (
            *common,
            prompt_text.HOME_REVIEW_GUIDE,
            prompt_text.HOME_DIFF_GUIDE,
            prompt_text.HOME_REVIEW_DECISION_GUIDE,
        )
    if kind == "memory":
        return (
            *common,
            prompt_text.MEMORY_TARGET_DAY_GUIDE,
            prompt_text.MEMORY_SOURCES_GUIDE,
            prompt_text.MEMORY_WRITING_GUIDE,
            prompt_text.MEMORY_REDIRECT_GUIDE,
        )
    raise ReflectionContractError(f"Unknown Reflection Turn kind: {kind}")
