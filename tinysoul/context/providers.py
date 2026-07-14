"""Provider-neutral dynamic Background entry catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from .errors import ContextInvariantError


@dataclass(frozen=True)
class BackgroundCatalog:
    """Current default and loadable top-level Background links."""

    owner: str
    default_links: tuple[str, ...] = field(default_factory=tuple)
    loadable_links: tuple[str, ...] = field(default_factory=tuple)
    evictable_default_links: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.owner, str) or not self.owner:
            raise ContextInvariantError("Background catalog owner must be non-empty")
        defaults = tuple(self.default_links)
        loadable = tuple(self.loadable_links)
        evictable_defaults = tuple(self.evictable_default_links)
        if any(not link for link in (*defaults, *loadable, *evictable_defaults)):
            raise ContextInvariantError("Background catalog links must be non-empty")
        if len(defaults) != len(set(defaults)) or len(loadable) != len(set(loadable)):
            raise ContextInvariantError("Background catalog links must be unique")
        if len(evictable_defaults) != len(set(evictable_defaults)):
            raise ContextInvariantError(
                "Evictable default Background links must be unique"
            )
        if not set(defaults).issubset(loadable):
            raise ContextInvariantError(
                "Default Background links must also be loadable"
            )
        if not set(evictable_defaults).issubset(defaults):
            raise ContextInvariantError(
                "Evictable default Background links must also be defaults"
            )
        object.__setattr__(self, "default_links", defaults)
        object.__setattr__(self, "loadable_links", loadable)
        object.__setattr__(self, "evictable_default_links", evictable_defaults)


class BackgroundEntryProvider(Protocol):
    def catalog(self, business_day: date) -> BackgroundCatalog:
        ...

    def load(self, link: str, business_day: date) -> str:
        ...
