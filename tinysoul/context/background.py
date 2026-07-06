"""Background context state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tinysoul.llm.messages import Message, SystemMessage

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


class BackgroundContext:
    """Ordered top-level content entries plus the day journal."""

    def __init__(self, *, journal: str = "") -> None:
        self._entries: dict[str, BackgroundEntry] = {}
        self._journal = journal

    @property
    def journal(self) -> str:
        return self._journal

    def set_journal(self, journal: str) -> None:
        self._journal = journal

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

    def render_messages(self) -> tuple[Message, ...]:
        messages: list[Message] = []
        if self._journal:
            messages.append(
                SystemMessage.from_text(self._journal, label="background:journal")
            )
        for entry in self._entries.values():
            messages.append(
                SystemMessage.from_text(entry.content, label=f"background:{entry.link}")
            )
        return tuple(messages)
