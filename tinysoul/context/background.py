"""Background context state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.llm.messages import Message, UserMessage
from tinysoul.infra.json import JsonObject, to_json_object

from .errors import ContextContractError, ContextInvariantError


class BackgroundSource(StrEnum):
    """How a background entry entered the context."""

    DEFAULT = "default"
    PHASE1 = "phase1"


@dataclass(frozen=True)
class BackgroundEntry:
    """One top-level content entry visible in the background context."""

    link: str
    content: str
    source: BackgroundSource = BackgroundSource.DEFAULT

    def __post_init__(self) -> None:
        if not self.link:
            raise ContextInvariantError("BackgroundEntry.link must be non-empty")
        if not self.content:
            raise ContextInvariantError("BackgroundEntry.content must be non-empty")
        if not isinstance(self.source, BackgroundSource):
            raise ContextInvariantError("BackgroundEntry.source must be a BackgroundSource")


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


@dataclass(frozen=True)
class SessionBackgroundItem:
    """One Session-owned message projected into BackgroundContext."""

    item_id: str
    content: JsonObject

    def __post_init__(self) -> None:
        if not self.item_id:
            raise ContextInvariantError(
                "SessionBackgroundItem.item_id must be non-empty"
            )
        object.__setattr__(self, "content", to_json_object(self.content))


@dataclass(frozen=True)
class SessionBackgroundSnapshot:
    """Immutable Session history projection for one Turn."""

    revision: int
    items: tuple[SessionBackgroundItem, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ContextInvariantError(
                "SessionBackgroundSnapshot.revision cannot be negative"
            )
        ids = tuple(item.item_id for item in self.items)
        if len(ids) != len(set(ids)):
            raise ContextInvariantError(
                "SessionBackgroundSnapshot.items must have unique ids"
            )


class BackgroundContext:
    """Ordered top-level content entries plus the day journal."""

    def __init__(self, *, journal: str = "") -> None:
        self._entries: dict[str, BackgroundEntry] = {}
        self._journal = journal
        self._session = SessionBackgroundSnapshot(revision=0)

    @property
    def journal(self) -> str:
        return self._journal

    def set_journal(self, journal: str) -> None:
        self._journal = journal

    def reset_session(self) -> None:
        self._session = SessionBackgroundSnapshot(revision=0)

    def reset_home(self, entries: tuple[BackgroundEntry, ...] = ()) -> None:
        self._entries = {entry.link: entry for entry in entries}

    def check_session_snapshot(self, snapshot: SessionBackgroundSnapshot) -> str:
        if snapshot.revision < self._session.revision:
            return (
                "Session background snapshot revision is stale: "
                f"current {self._session.revision}, received {snapshot.revision}"
            )
        if snapshot.revision == self._session.revision and snapshot != self._session:
            return (
                "Session background snapshot conflicts with current revision: "
                f"{snapshot.revision}"
            )
        return ""

    def apply_session_snapshot(self, snapshot: SessionBackgroundSnapshot) -> None:
        problem = self.check_session_snapshot(snapshot)
        if problem:
            raise ContextInvariantError(problem)
        self._session = snapshot

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

    def check_patch(self, patch: BackgroundPatch, *, loadable_links: tuple[str, ...]) -> str:
        """Return a model-facing patch problem, or empty when applicable."""

        return self._check_patch_against_loaded(
            patch,
            loaded=set(self.links()),
            loadable_links=loadable_links,
        )

    def check_patch_sequence(
        self,
        patches: tuple[BackgroundPatch, ...],
        *,
        loadable_links: tuple[str, ...],
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
            )
            problems.append(problem)
            if not problem:
                loaded = next_loaded
        return tuple(problems)

    def render_messages(self) -> tuple[Message, ...]:
        return (*self.render_session_messages(), *self.render_home_messages())

    def render_session_messages(self) -> tuple[Message, ...]:
        return tuple(
            UserMessage.from_json(
                item.content,
                label=f"background:session:{item.item_id}",
            )
            for item in self._session.items
        )

    def render_home_messages(self) -> tuple[Message, ...]:
        messages: list[Message] = []
        if self._journal:
            messages.append(
                UserMessage.from_text(self._journal, label="background:journal")
            )
        for entry in self._entries.values():
            messages.append(
                UserMessage.from_text(entry.content, label=f"background:{entry.link}")
            )
        return tuple(messages)

    def evict_phase1_for_budget(self, *, required_chars: int) -> BackgroundEvictionReport:
        if required_chars <= 0:
            return BackgroundEvictionReport(changed=False, reclaimed_chars=0)
        reclaimed = 0
        evicted: list[str] = []
        for entry in tuple(self._entries.values()):
            if entry.source is not BackgroundSource.PHASE1:
                continue
            del self._entries[entry.link]
            evicted.append(entry.link)
            reclaimed += len(entry.link) + len(entry.content) + 24
            if reclaimed >= required_chars:
                break
        return BackgroundEvictionReport(
            changed=bool(evicted),
            reclaimed_chars=reclaimed,
            evicted_links=tuple(evicted),
        )

    def _check_patch_against_loaded(
        self,
        patch: BackgroundPatch,
        *,
        loaded: set[str],
        loadable_links: tuple[str, ...],
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
        for link in patch.load_links:
            if link not in loadable:
                return f"Unknown loadable background link: {link}"
        for link in patch.evict_links:
            if link not in loaded:
                return f"Background link is not loaded: {link}"
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
