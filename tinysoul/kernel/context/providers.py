"""Provider-neutral dynamic Background entry catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from tinysoul.infra.references import ResourceLocator

from .errors import ContextInvariantError


@dataclass(frozen=True)
class BackgroundCatalogItem:
    """Bounded discovery metadata for one loadable Background entry."""

    ref: str
    title: str
    description: str
    resolved_locator: ResourceLocator | None = None

    def __post_init__(self) -> None:
        for name in ("ref", "title", "description"):
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
    """Current default and loadable top-level Background refs."""

    owner: str
    default_refs: tuple[str, ...] = field(default_factory=tuple)
    loadable_refs: tuple[str, ...] = field(default_factory=tuple)
    evictable_default_refs: tuple[str, ...] = field(default_factory=tuple)
    items: tuple[BackgroundCatalogItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.owner, str) or not self.owner:
            raise ContextInvariantError("Background catalog owner must be non-empty")
        defaults = tuple(self.default_refs)
        loadable = tuple(self.loadable_refs)
        evictable_defaults = tuple(self.evictable_default_refs)
        items = tuple(self.items)
        if any(not isinstance(item, BackgroundCatalogItem) for item in items):
            raise ContextInvariantError(
                "Background catalog items must be BackgroundCatalogItem values"
            )
        if any(not ref for ref in (*defaults, *loadable, *evictable_defaults)):
            raise ContextInvariantError("Background catalog refs must be non-empty")
        if len(defaults) != len(set(defaults)) or len(loadable) != len(set(loadable)):
            raise ContextInvariantError("Background catalog refs must be unique")
        if len(evictable_defaults) != len(set(evictable_defaults)):
            raise ContextInvariantError(
                "Evictable default Background refs must be unique"
            )
        if not set(defaults).issubset(loadable):
            raise ContextInvariantError("Default Background refs must also be loadable")
        if not set(evictable_defaults).issubset(defaults):
            raise ContextInvariantError(
                "Evictable default Background refs must also be defaults"
            )
        item_refs = tuple(item.ref for item in items)
        if len(item_refs) != len(set(item_refs)):
            raise ContextInvariantError("Background catalog item refs must be unique")
        if not set(item_refs).issubset(loadable):
            raise ContextInvariantError(
                "Background catalog item refs must also be loadable"
            )
        object.__setattr__(self, "default_refs", defaults)
        object.__setattr__(self, "loadable_refs", loadable)
        object.__setattr__(self, "evictable_default_refs", evictable_defaults)
        object.__setattr__(self, "items", items)


class BackgroundEntryProvider(Protocol):
    async def catalog(self, active_day: date) -> BackgroundCatalog: ...

    async def load(self, ref: str, active_day: date) -> str: ...


@dataclass(frozen=True)
class SegmentSelectionView:
    """Current navigation choices; content remains in the segment."""

    available: tuple[str, ...] = ()
    loaded: tuple[str, ...] = ()
    protected: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("available", "loaded", "protected"):
            refs = tuple(getattr(self, name))
            if any(not isinstance(ref, str) or not ref for ref in refs) or len(
                set(refs)
            ) != len(refs):
                raise ContextInvariantError(
                    "Segment selection references must be unique text"
                )
            object.__setattr__(self, name, refs)
        if not set(self.loaded).issubset(self.available) or not set(
            self.protected
        ).issubset(self.available):
            raise ContextInvariantError(
                "Segment selection state is outside its catalog"
            )
