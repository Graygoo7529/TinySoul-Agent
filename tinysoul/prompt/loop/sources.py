"""Standard loop system source helpers."""

from __future__ import annotations

from pathlib import Path

from tinysoul.prompt.source import FilePromptRef, PromptSource


def home_loop_system_sources(
    home_root: str | Path,
    *,
    include_agent: bool = True,
    include_identity: bool = True,
    include_user: bool = True,
    required: bool = False,
) -> list[PromptSource]:
    """Return standard home-level loop system sources.

    The helper only builds source declarations. File loading and system message
    assembly remain centralized in ``build_loop_system``.
    """

    root = Path(home_root)
    sources: list[PromptSource] = []

    if include_agent:
        sources.append(
            FilePromptRef(
                name="home_agent",
                root=root,
                path="AGENT.md",
                required=required,
            )
        )
    if include_identity:
        sources.append(
            FilePromptRef(
                name="home_identity",
                root=root,
                path="IDENTITY.md",
                required=required,
            )
        )
    if include_user:
        sources.append(
            FilePromptRef(
                name="home_user",
                root=root,
                path="USER.md",
                required=required,
            )
        )

    return sources


__all__ = ["home_loop_system_sources"]
