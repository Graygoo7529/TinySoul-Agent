"""Provider-neutral dynamic Background entry catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from .errors import ContextInvariantError


@dataclass(frozen=True)
class BackgroundCatalogItem:
    """Bounded discovery metadata for one loadable Background entry."""

    link: str
    title: str
    description: str

    def __post_init__(self) -> None:
        for name in ("link", "title", "description"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContextInvariantError(
                    f"Background catalog item {name} must be non-empty text"
                )
        if any(character in self.title for character in "\r\n") or any(
            character in self.description for character in "\r\n"
        ):
            raise ContextInvariantError(
                "Background catalog item title and description must be one line"
            )


@dataclass(frozen=True)
class BackgroundCatalog:
    """Current default and loadable top-level Background links."""

    owner: str
    default_links: tuple[str, ...] = field(default_factory=tuple)
    loadable_links: tuple[str, ...] = field(default_factory=tuple)
    evictable_default_links: tuple[str, ...] = field(default_factory=tuple)
    items: tuple[BackgroundCatalogItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.owner, str) or not self.owner:
            raise ContextInvariantError("Background catalog owner must be non-empty")
        defaults = tuple(self.default_links)
        loadable = tuple(self.loadable_links)
        evictable_defaults = tuple(self.evictable_default_links)
        items = tuple(self.items)
        if any(not isinstance(item, BackgroundCatalogItem) for item in items):
            raise ContextInvariantError(
                "Background catalog items must be BackgroundCatalogItem values"
            )
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
        item_links = tuple(item.link for item in items)
        if len(item_links) != len(set(item_links)):
            raise ContextInvariantError("Background catalog item links must be unique")
        if not set(item_links).issubset(loadable):
            raise ContextInvariantError(
                "Background catalog item links must also be loadable"
            )
        object.__setattr__(self, "default_links", defaults)
        object.__setattr__(self, "loadable_links", loadable)
        object.__setattr__(self, "evictable_default_links", evictable_defaults)
        object.__setattr__(self, "items", items)


class BackgroundEntryProvider(Protocol):
    def catalog(self, business_day: date) -> BackgroundCatalog:
        ...

    def load(self, link: str, business_day: date) -> str:
        ...
