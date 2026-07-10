"""Agent Home module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.filesystem import TextPrefixRead, read_text_prefix

from .config import AgentHomeSettings
from .errors import AgentHomeContractError, AgentHomeIOError, AgentHomeRuntimeCopyRequired
from .layout import AgentHomeLayout
from .links import HomeLink, HomePromptMountLink, HomeResourceLink, HomeTopLink, parse_home_link
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

    def loadable_background_links(self) -> tuple[str, ...]:
        """Return the top-level catalog without materializing runtime copies."""

        return tuple(str(link) for link in self._layout.top_links())

    def read_top(self, link: HomeTopLink | str) -> str:
        parsed = HomeTopLink.parse(link) if isinstance(link, str) else link
        source = self._layout.source_for_top(parsed)
        if not source.is_file():
            raise AgentHomeContractError(f"Home top-level file does not exist: {source}")
        return _read_text(self._runtime_read_path(str(parsed), source))

    def read_prompt_mount(self, link: HomePromptMountLink | str) -> str:
        parsed = HomePromptMountLink.parse(link) if isinstance(link, str) else link
        source = self._layout.source_for_prompt_mount(parsed)
        if not source.is_file():
            raise AgentHomeContractError(f"Home prompt mount file does not exist: {source}")
        return _read_text(self._runtime_read_path(str(parsed), source))

    def read_resource(
        self,
        link: HomeResourceLink | str,
        *,
        max_chars: int | None = None,
    ) -> HomeResourceRead:
        parsed_link = parse_home_link(link) if isinstance(link, str) else link
        if not isinstance(parsed_link, HomeResourceLink):
            raise AgentHomeContractError(
                "Home resource read requires a progressive resource link"
            )
        parsed = parsed_link
        limit = self._max_read_chars if max_chars is None else max_chars
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise AgentHomeContractError("Home resource read limit must be positive")
        source = self._layout.source_for_resource(parsed)
        if not source.is_file():
            raise AgentHomeContractError(f"Home resource file does not exist: {source}")
        read = _read_text_prefix(self._runtime_read_path(str(parsed), source), limit)
        return HomeResourceRead(
            link=str(parsed),
            text=read.text,
            truncated=read.truncated,
        )

    def guidance_for_domain(self, domain: str) -> str | None:
        if not domain:
            return None
        link = HomePromptMountLink("how_domain", domain)
        try:
            return self.read_prompt_mount(link)
        except AgentHomeContractError:
            return None

    def guidance_for_action(self, domain: str, action_name: str) -> str | None:
        if not domain or not action_name:
            return None
        action_key = action_name
        prefix = f"{domain}."
        if action_name.startswith(prefix):
            action_key = action_name[len(prefix) :]
        link = HomePromptMountLink("how_action", f"{domain}/{action_key}")
        try:
            return self.read_prompt_mount(link)
        except AgentHomeContractError:
            return None

    def ensure_runtime_copy(self, link: HomeLink) -> None:
        if isinstance(link, HomeTopLink):
            source = self._layout.source_for_top(link)
        elif isinstance(link, HomeResourceLink):
            source = self._layout.source_for_resource(link)
        else:
            source = self._layout.source_for_prompt_mount(link)
        runtime = self._layout.runtime_for_source(source)
        self._runtime_copy.ensure_source_copy(source, runtime)

    def _runtime_read_path(self, link: str, source: Path) -> Path:
        runtime = self._layout.runtime_for_source(source)
        if not runtime.is_file():
            raise AgentHomeRuntimeCopyRequired(
                link,
                source_path=source,
                runtime_path=runtime,
            )
        return runtime


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


def _read_text_prefix(path: Path, max_chars: int) -> TextPrefixRead:
    try:
        return read_text_prefix(path, max_chars=max_chars)
    except UnicodeDecodeError as exc:
        raise AgentHomeContractError(
            f"Agent Home file is not readable as UTF-8 text: {path}"
        ) from exc
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to read Agent Home file: {exc}") from exc
