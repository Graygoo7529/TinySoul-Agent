"""Provider-neutral dynamic Background entry catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .errors import ContextInvariantError


@dataclass(frozen=True)
class BackgroundCatalog:
    """Current default and loadable top-level Background links."""

    default_links: tuple[str, ...] = field(default_factory=tuple)
    loadable_links: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        defaults = tuple(self.default_links)
        loadable = tuple(self.loadable_links)
        if any(not link for link in (*defaults, *loadable)):
            raise ContextInvariantError("Background catalog links must be non-empty")
        if len(defaults) != len(set(defaults)) or len(loadable) != len(set(loadable)):
            raise ContextInvariantError("Background catalog links must be unique")
        if not set(defaults).issubset(loadable):
            raise ContextInvariantError(
                "Default Background links must also be loadable"
            )
        object.__setattr__(self, "default_links", defaults)
        object.__setattr__(self, "loadable_links", loadable)


class BackgroundEntryProvider(Protocol):
    def catalog(self) -> BackgroundCatalog:
        ...

    def load(self, link: str) -> str:
        ...


@dataclass(frozen=True)
class EmptyBackgroundEntryProvider:
    def catalog(self) -> BackgroundCatalog:
        return BackgroundCatalog()

    def load(self, link: str) -> str:
        raise ContextInvariantError(f"Unknown dynamic Background link: {link}")
