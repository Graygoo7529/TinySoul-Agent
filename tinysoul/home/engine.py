"""Agent Home module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AgentHomeSettings
from .errors import AgentHomeContractError, AgentHomeIOError
from .layout import AgentHomeLayout
from .links import HomeLink, HomeResourceLink, HomeTopLink, parse_home_link
from .runtime_copy import AgentHomeRuntimeCopyManager


@dataclass(frozen=True)
class HomeBackgroundEntry:
    """A background entry provided by Agent Home."""

    link: str
    content: str


@dataclass(frozen=True)
class HomeResourceRead:
    """A bounded read result for an Agent Home resource."""

    link: str
    text: str
    truncated: bool


class AgentHomeEngine:
    """Agent Home resource management entry point."""

    def __init__(
        self,
        *,
        layout: AgentHomeLayout,
        runtime_copy: AgentHomeRuntimeCopyManager,
        max_read_chars: int,
    ) -> None:
        self._layout = layout
        self._runtime_copy = runtime_copy
        self._max_read_chars = max_read_chars

    @property
    def layout(self) -> AgentHomeLayout:
        return self._layout

    def parse_link(self, value: str) -> HomeLink:
        return parse_home_link(value)

    def default_background_entries(self) -> tuple[HomeBackgroundEntry, ...]:
        core = HomeTopLink("agent", "core")
        return (HomeBackgroundEntry(link=str(core), content=self.read_top(core)),)

    def loadable_background_entries(self) -> tuple[HomeBackgroundEntry, ...]:
        entries: list[HomeBackgroundEntry] = []
        for link in self._layout.top_links():
            try:
                entries.append(HomeBackgroundEntry(link=str(link), content=self.read_top(link)))
            except AgentHomeContractError:
                continue
        return tuple(entries)

    def read_top(self, link: HomeTopLink | str) -> str:
        parsed = HomeTopLink.parse(link) if isinstance(link, str) else link
        source = self._layout.source_for_top(parsed)
        if not source.is_file():
            raise AgentHomeContractError(f"Home top-level file does not exist: {source}")
        return _read_text(source)

    def read_resource(
        self,
        link: HomeResourceLink | str,
        *,
        max_chars: int | None = None,
    ) -> HomeResourceRead:
        parsed = HomeResourceLink.parse(link) if isinstance(link, str) else link
        limit = max_chars or self._max_read_chars
        if limit <= 0:
            raise AgentHomeContractError("Home resource read limit must be positive")
        source = self._layout.source_for_resource(parsed)
        if not source.is_file():
            raise AgentHomeContractError(f"Home resource file does not exist: {source}")
        text = _read_text(source)
        truncated = len(text) > limit
        if truncated:
            text = text[:limit]
        return HomeResourceRead(link=str(parsed), text=text, truncated=truncated)

    def guidance_for_domain(self, domain: str) -> str | None:
        if not domain:
            return None
        link = HomeTopLink("how_action", domain)
        try:
            return self.read_top(link)
        except AgentHomeContractError:
            return None

    def ensure_runtime_copy(self, link: HomeLink) -> None:
        if isinstance(link, HomeTopLink):
            source = self._layout.source_for_top(link)
        else:
            source = self._layout.source_for_resource(link)
        runtime = self._layout.runtime_for_source(source)
        self._runtime_copy.ensure_source_copy(source, runtime)


class AgentHomeEngineBuilder:
    """Build an AgentHomeEngine from parsed settings."""

    def __init__(self, settings: AgentHomeSettings) -> None:
        self._settings = settings

    def build(self) -> AgentHomeEngine:
        if not self._settings.original_root.exists():
            raise AgentHomeIOError("Agent Home root does not exist")
        if not self._settings.original_root.is_dir():
            raise AgentHomeIOError("Agent Home root must be a directory")
        return AgentHomeEngine(
            layout=AgentHomeLayout(self._settings),
            runtime_copy=AgentHomeRuntimeCopyManager(),
            max_read_chars=self._settings.max_read_chars,
        )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to read Agent Home file: {exc}") from exc
