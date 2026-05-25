"""Prompt source declarations and resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from tinysoul.infra.resources import (
    LoadedTextResource,
    loaded_text_from_inline,
    load_text_from_filesystem,
    load_text_from_package,
)


@dataclass(frozen=True)
class InlinePromptSource:
    """Inline prompt text supplied by a caller."""

    name: str
    content: str


@dataclass(frozen=True)
class FilePromptRef:
    """Prompt text loaded from a configured filesystem root."""

    name: str
    root: str | Path
    path: str
    required: bool = True


@dataclass(frozen=True)
class BuiltinPromptRef:
    """Prompt text loaded from TinySoul package data."""

    name: str
    package: str
    resource: str
    required: bool = True


PromptSource: TypeAlias = InlinePromptSource | FilePromptRef | BuiltinPromptRef


def resolve_prompt_source(source: PromptSource) -> LoadedTextResource | None:
    """Resolve a prompt source declaration into loaded text."""

    if isinstance(source, InlinePromptSource):
        return loaded_text_from_inline(source.name, source.content)
    if isinstance(source, FilePromptRef):
        return load_text_from_filesystem(
            source.name,
            source.root,
            source.path,
            required=source.required,
        )
    if isinstance(source, BuiltinPromptRef):
        return load_text_from_package(
            source.name,
            source.package,
            source.resource,
            required=source.required,
        )
    raise TypeError(f"Unsupported prompt source: {type(source).__name__}")


def resolve_prompt_sources(
    sources: list[PromptSource] | None,
) -> list[LoadedTextResource]:
    """Resolve prompt sources, skipping missing optional resources."""

    loaded: list[LoadedTextResource] = []
    for source in sources or []:
        resource = resolve_prompt_source(source)
        if resource is not None:
            loaded.append(resource)
    return loaded
