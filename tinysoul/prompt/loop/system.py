"""Loop-level system message assembly."""

from __future__ import annotations

from tinysoul.infra.resources import LoadedTextResource
from tinysoul.prompt.source import BuiltinPromptRef, PromptSource, resolve_prompt_sources


QUERY_LOOP_SYSTEM_REF = BuiltinPromptRef(
    name="query_loop_system",
    package="tinysoul.prompt.loop",
    resource="markdown/query_loop.system.md",
)


def resources_to_system_messages(
    resources: list[LoadedTextResource],
) -> list[dict[str, str]]:
    """Convert loaded resources to OpenAI-style system messages."""

    messages: list[dict[str, str]] = []
    for resource in resources:
        content = resource.content.strip()
        if content:
            messages.append({"role": "system", "content": content})
    return messages


def build_loop_system(
    loop_system: list[PromptSource] | None = None,
    *,
    include_builtin_query_loop_system: bool = True,
) -> list[dict[str, str]]:
    """Build loop-level system messages from external and builtin sources."""

    sources = list(loop_system or [])
    if include_builtin_query_loop_system:
        sources.append(QUERY_LOOP_SYSTEM_REF)
    return resources_to_system_messages(resolve_prompt_sources(sources))


__all__ = [
    "QUERY_LOOP_SYSTEM_REF",
    "build_loop_system",
    "resources_to_system_messages",
]
