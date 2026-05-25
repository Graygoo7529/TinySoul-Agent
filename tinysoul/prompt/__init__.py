"""Prompt resources and system assembly for TinySoul."""

from .source import (
    BuiltinPromptRef,
    FilePromptRef,
    InlinePromptSource,
    PromptSource,
    resolve_prompt_source,
    resolve_prompt_sources,
)
from .loop import QUERY_LOOP_SYSTEM_REF, build_loop_system, home_loop_system_sources

__all__ = [
    "BuiltinPromptRef",
    "FilePromptRef",
    "InlinePromptSource",
    "PromptSource",
    "QUERY_LOOP_SYSTEM_REF",
    "build_loop_system",
    "home_loop_system_sources",
    "resolve_prompt_source",
    "resolve_prompt_sources",
]
