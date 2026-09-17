"""Background context state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from tinysoul.llm.messages import Message, UserMessage
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import Signal

from .errors import ContextContractError, ContextInvariantError
from .providers import BackgroundCatalog, BackgroundEntryProvider, SegmentSelectionView

if TYPE_CHECKING:
    from .segments import SegmentDescriptor, SegmentRegistration, SegmentReclaim, TurnInfo


class BackgroundSource(StrEnum):
    """How a background entry entered the context."""

    DEFAULT = "default"
    AUTOMATIC = "automatic"
    PHASE1 = "phase1"


@dataclass(frozen=True)
class BackgroundEntry:
    """One top-level content entry visible in the background context."""

    link: str
    content: str
    source: BackgroundSource = BackgroundSource.DEFAULT
    owner: str = "context"
    evictable: bool = False

    def __post_init__(self) -> None:
        if not self.link:
            raise ContextInvariantError("BackgroundEntry.link must be non-empty")
        if not self.content:
            raise ContextInvariantError("BackgroundEntry.content must be non-empty")
        if not isinstance(self.source, BackgroundSource):
            raise ContextInvariantError("BackgroundEntry.source must be a BackgroundSource")
        if not isinstance(self.owner, str) or not self.owner:
            raise ContextInvariantError("BackgroundEntry.owner must be non-empty")
        if not isinstance(self.evictable, bool):
            raise ContextInvariantError("BackgroundEntry.evictable must be a boolean")


@dataclass(frozen=True)
class BackgroundPatch:
    """A background load/evict request parsed from a signal payload."""

    load_links: tuple[str, ...] = field(default_factory=tuple)
    evict_links: tuple[str, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        return not (self.load_links or self.evict_links)


@dataclass(frozen=True)
class BackgroundEvictionReport:
    changed: bool
    reclaimed_chars: int
    evicted_links: tuple[str, ...] = field(default_factory=tuple)


class BackgroundContext:
    """Ordered top-level content entries plus the day journal."""

    def __init__(self, *, journal: str = "") -> None:
        self._entries: dict[str, BackgroundEntry] = {}
        self._journal = journal
        self._catalogs: tuple[BackgroundCatalog, ...] = ()

    @property
    def journal(self) -> str:
        return self._journal

    def set_journal(self, journal: str) -> None:
        self._journal = journal

    def reset_catalogs(self, catalogs: tuple[BackgroundCatalog, ...] = ()) -> None:
        self._catalogs = tuple(catalogs)

    def reset_entries(self, entries: tuple[BackgroundEntry, ...] = ()) -> None:
        self._entries = {entry.link: entry for entry in entries}

    def has(self, link: str) -> bool:
        return link in self._entries

    def load(self, entry: BackgroundEntry) -> None:
        """Load or replace one top-level content entry."""

        self._entries[entry.link] = entry

    def evict(self, link: str) -> None:
        if link not in self._entries:
            raise ContextContractError(f"Unknown background entry link: {link}")
        del self._entries[link]

    def entries(self) -> tuple[BackgroundEntry, ...]:
        return tuple(self._entries.values())

    def links(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def evictable_links(self) -> tuple[str, ...]:
        return tuple(
            entry.link for entry in self._entries.values() if entry.evictable
        )

    def check_patch(
        self,
        patch: BackgroundPatch,
        *,
        loadable_links: tuple[str, ...],
        evictable_links: tuple[str, ...],
    ) -> str:
        """Return a model-facing patch problem, or empty when applicable."""

        return self._check_patch_against_loaded(
            patch,
            loaded=set(self.links()),
            loadable_links=loadable_links,
            evictable_links=evictable_links,
        )

    def check_patch_sequence(
        self,
        patches: tuple[BackgroundPatch, ...],
        *,
        loadable_links: tuple[str, ...],
        evictable_links: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Validate patches against a projected loaded-link state."""

        loaded = set(self.links())
        problems: list[str] = []
        for patch in patches:
            next_loaded = set(loaded)
            problem = self._check_patch_against_loaded(
                patch,
                loaded=next_loaded,
                loadable_links=loadable_links,
                evictable_links=evictable_links,
            )
            problems.append(problem)
            if not problem:
                loaded = next_loaded
        return tuple(problems)

    def render_messages(self) -> tuple[Message, ...]:
        return self.render_background_messages()

    def render_background_messages(self) -> tuple[Message, ...]:
        messages: list[Message] = []
        if self._journal:
            messages.append(
                UserMessage.from_text(self._journal, label="background:journal")
            )
        for catalog in self._catalogs:
            if not catalog.items:
                continue
            messages.append(
                UserMessage.from_json(
                    {
                        "owner": catalog.owner,
                        "items": [
                            {
                                "link": item.link,
                                "title": item.title,
                                "description": item.description,
                            }
                            for item in catalog.items
                        ],
                    },
                    label=f"background:catalog:{catalog.owner}",
                )
            )
        for entry in self._entries.values():
            messages.append(
                UserMessage.from_text(entry.content, label=f"background:{entry.link}")
            )
        return tuple(messages)

    def evict_for_budget(self, *, required_chars: int) -> BackgroundEvictionReport:
        if required_chars <= 0:
            return BackgroundEvictionReport(changed=False, reclaimed_chars=0)
        reclaimed = 0
        evicted: list[str] = []
        for source in (BackgroundSource.PHASE1, BackgroundSource.AUTOMATIC):
            for entry in tuple(self._entries.values()):
                if entry.source is not source or not entry.evictable:
                    continue
                del self._entries[entry.link]
                evicted.append(entry.link)
                reclaimed += len(entry.link) + len(entry.content) + 24
                if reclaimed >= required_chars:
                    break
            if reclaimed >= required_chars:
                break
        return BackgroundEvictionReport(
            changed=bool(evicted),
            reclaimed_chars=reclaimed,
            evicted_links=tuple(evicted),
        )

    @staticmethod
    def _check_patch_against_loaded(
        patch: BackgroundPatch,
        *,
        loaded: set[str],
        loadable_links: tuple[str, ...],
        evictable_links: tuple[str, ...],
    ) -> str:
        duplicate = _first_duplicate(patch.load_links)
        if duplicate:
            return f"Background patch contains duplicate load link: {duplicate}"
        duplicate = _first_duplicate(patch.evict_links)
        if duplicate:
            return f"Background patch contains duplicate evict link: {duplicate}"
        conflict = sorted(set(patch.load_links) & set(patch.evict_links))
        if conflict:
            return f"Background patch cannot load and evict the same link: {conflict[0]}"
        if patch.is_empty():
            return "Background patch contains no links"
        loadable = set(loadable_links)
        evictable = set(evictable_links)
        for link in patch.load_links:
            if link not in loadable:
                return f"Unknown loadable background link: {link}"
        for link in patch.evict_links:
            if link not in loaded:
                return f"Background link is not loaded: {link}"
            if link not in evictable:
                return f"Background link is not evictable: {link}"
            loaded.remove(link)
        for link in patch.load_links:
            loaded.add(link)
        return ""


def _first_duplicate(values: tuple[str, ...]) -> str:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return ""


def check_background_patches(
    view: SegmentSelectionView, patches: tuple[BackgroundPatch, ...],
) -> tuple[str, ...]:
    loaded = set(view.loaded)
    problems: list[str] = []
    for patch in patches:
        candidate = set(loaded)
        problem = BackgroundContext._check_patch_against_loaded(
            patch, loaded=candidate, loadable_links=view.available,
            evictable_links=tuple(ref for ref in view.available if ref not in view.protected),
        )
        problems.append(problem)
        if not problem:
            loaded = candidate
    return tuple(problems)


@dataclass(frozen=True)
class HeapUpdate:
    selection: BackgroundPatch = field(default_factory=BackgroundPatch)
    refresh: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.selection, BackgroundPatch) or not isinstance(self.refresh, bool):
            raise ContextContractError("Heap update must use typed selection and refresh")
        if not self.refresh and self.selection.is_empty():
            raise ContextContractError("Heap update cannot be empty")


def decode_heap_update(signal: Signal) -> HeapUpdate:
    fields = signal.payload
    if set(fields) - {"load_links", "evict_links", "refresh"}:
        raise ContextContractError("Heap update contains unsupported fields")
    refs: list[tuple[str, ...]] = []
    for name in ("load_links", "evict_links"):
        value = fields.get(name, [])
        if not isinstance(value, list) or any(not isinstance(ref, str) or not ref for ref in value):
            raise ContextContractError("Heap selection requires resource references")
        refs.append(tuple(ref for ref in value if isinstance(ref, str)))
    refresh = fields.get("refresh", False)
    if not isinstance(refresh, bool):
        raise ContextContractError("Heap refresh must be a boolean")
    return HeapUpdate(BackgroundPatch(*refs), refresh)


@dataclass(frozen=True)
class HeapCandidate:
    catalog: BackgroundCatalog
    entries: tuple[BackgroundEntry, ...]


class HeapSegment:
    """Reusable Turn-local heap algorithm; the injected owner reads all content."""

    def __init__(self, source: BackgroundEntryProvider, day: date, candidate: HeapCandidate) -> None:
        self._source = source
        self._day = day
        self._catalog = candidate.catalog
        self._view = BackgroundContext()
        self.install(candidate)

    def selection_view(self) -> SegmentSelectionView:
        return SegmentSelectionView(
            self._catalog.loadable_links, self._view.links(),
            tuple(ref for ref in self._catalog.default_links if ref not in self._catalog.evictable_default_links),
        )

    async def prepare(self, updates: tuple[HeapUpdate, ...]) -> HeapCandidate:
        catalog = self._catalog
        entries = {entry.link: entry for entry in self._view.entries()}
        for update in updates:
            if update.refresh:
                catalog = await self._source.catalog(self._day)
                if catalog.owner != self._catalog.owner:
                    raise ContextInvariantError("Heap refresh changed its owner")
                selected = tuple(dict.fromkeys((*catalog.default_links, *entries)))
                entries = {
                    ref: await _heap_entry(self._source, self._day, catalog, ref, entries.get(ref))
                    for ref in selected if ref in catalog.loadable_links
                }
            patch = update.selection
            if patch.is_empty():
                continue
            protected = tuple(ref for ref in catalog.default_links if ref not in catalog.evictable_default_links)
            problems = check_background_patches(
                SegmentSelectionView(catalog.loadable_links, tuple(entries), protected), (patch,),
            )
            if problems[0]:
                raise ContextContractError(problems[0])
            for ref in patch.evict_links:
                del entries[ref]
            for ref in patch.load_links:
                if ref not in entries:
                    entries[ref] = await _heap_entry(self._source, self._day, catalog, ref)
        return HeapCandidate(catalog, tuple(entries.values()))

    def install(self, prepared: HeapCandidate) -> None:
        self._catalog = prepared.catalog
        self._view.reset_catalogs((prepared.catalog,))
        self._view.reset_entries(prepared.entries)

    def render(self) -> tuple[Message, ...]:
        return self._view.render_messages()

    def seal(self) -> JsonObject:
        return {"loaded_refs": list(self._view.links())}

    def reclaim(self, required_chars: int) -> SegmentReclaim:
        from .segments import SegmentReclaim
        report = self._view.evict_for_budget(required_chars=required_chars)
        return SegmentReclaim(report.reclaimed_chars, report.evicted_links)

    async def close(self) -> None:
        self._view.reset_entries()
        self._view.reset_catalogs()


async def _heap_entry(
    source: BackgroundEntryProvider, day: date, catalog: BackgroundCatalog,
    ref: str, previous: BackgroundEntry | None = None,
) -> BackgroundEntry:
    content = await source.load(ref, day)
    if ref in catalog.default_links:
        evictable = ref in catalog.evictable_default_links
        origin = BackgroundSource.AUTOMATIC if evictable else BackgroundSource.DEFAULT
    else:
        evictable = True
        origin = previous.source if previous is not None else BackgroundSource.PHASE1
    return BackgroundEntry(ref, content, origin, catalog.owner, evictable)


class HeapSegmentProvider:
    def __init__(self, source: BackgroundEntryProvider, *, owner: str) -> None:
        self._source = source
        self._owner = owner

    async def open(self, info: TurnInfo) -> HeapSegment:
        catalog = await self._source.catalog(info.day)
        if catalog.owner != self._owner:
            raise ContextInvariantError("Heap catalog belongs to another registered owner")
        candidate = HeapCandidate(catalog, tuple([
            await _heap_entry(self._source, info.day, catalog, ref) for ref in catalog.default_links
        ]))
        return HeapSegment(self._source, info.day, candidate)


def heap_segment_registration(
    descriptor: SegmentDescriptor, source: BackgroundEntryProvider, *, signal_name: str,
) -> SegmentRegistration[HeapUpdate, HeapCandidate]:
    from .segments import SegmentRegistration, SegmentShape
    if descriptor.shape is not SegmentShape.HEAP:
        raise ContextContractError("Heap provider requires heap shape")
    return SegmentRegistration(
        descriptor, HeapSegmentProvider(source, owner=descriptor.owner), signal_name,
        HeapUpdate, decode_heap_update,
    )
