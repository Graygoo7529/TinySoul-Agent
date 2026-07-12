"""Agent Home module assembly facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tinysoul.infra.filesystem import TextPrefixRead, read_text_prefix
from tinysoul.loop.day import BusinessDay

from .config import AgentHomeSettings
from .errors import (
    AgentHomeContractError,
    AgentHomeIOError,
    AgentHomeInvariantError,
    AgentHomeRuntimeCopyRequired,
)
from .layout import AgentHomeLayout
from .links import HomeLink, HomePromptMountLink, HomeResourceLink, HomeTopLink, parse_home_link
from .overlay import HomeOverlayManager, HomeOverlayRecord, HomeOverlayState


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
    digest: str


@dataclass(frozen=True)
class HomeResourceMutation:
    """Metadata-only result of a current-day Home overlay mutation."""

    link: str
    state: HomeOverlayState
    digest: str
    baseline_digest: str
    size: int


class AgentHomeEngine:
    """Agent Home resource management entry point."""

    def __init__(
        self,
        *,
        layout: AgentHomeLayout,
        overlay: HomeOverlayManager,
        max_read_chars: int,
        max_write_chars: int,
    ) -> None:
        self._layout = layout
        self._overlay = overlay
        self._max_read_chars = max_read_chars
        self._max_write_chars = max_write_chars

    @property
    def layout(self) -> AgentHomeLayout:
        return self._layout

    @property
    def active_day(self) -> BusinessDay | None:
        return self._overlay.active_day

    @property
    def original_root(self) -> Path:
        return self._layout.settings.original_root

    @property
    def runtime_root(self) -> Path:
        return self._layout.settings.runtime_root

    def initialize_day(self, day: BusinessDay) -> None:
        self._overlay.initialize_day(day)

    def require_day(self, day: BusinessDay) -> None:
        self._overlay.require_day(day)

    def reconcile(self) -> None:
        self._overlay.reconcile()

    def archive_day(self, day: BusinessDay, *, target: Path) -> None:
        self._overlay.archive_day(day, target=target)

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
        if parsed.space == "memory":
            return _read_text(source)
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
        if parsed.space == "memory":
            if not source.is_file():
                raise AgentHomeContractError(
                    f"Home memory resource does not exist: {source}"
                )
            path = source
            digest = _file_digest(path)
        else:
            path = self._runtime_read_path(str(parsed), source)
            effective = self._overlay.effective(
                self._layout.relative_for_source(source)
            )
            if effective is None:
                raise AgentHomeInvariantError(
                    f"Home resource did not resolve through overlay: {parsed}"
                )
            digest = effective.digest
        read = _read_text_prefix(path, limit)
        return HomeResourceRead(
            link=str(parsed),
            text=read.text,
            truncated=read.truncated,
            digest=digest,
        )

    def guidance_for_domain(self, domain: str) -> str | None:
        if not domain:
            return None
        link = HomePromptMountLink("how_domain", domain)
        return self._read_optional_prompt_mount(link)

    def guidance_for_action(self, domain: str, action_name: str) -> str | None:
        if not domain or not action_name:
            return None
        action_key = action_name
        prefix = f"{domain}."
        if action_name.startswith(prefix):
            action_key = action_name[len(prefix) :]
        link = HomePromptMountLink("how_action", f"{domain}/{action_key}")
        return self._read_optional_prompt_mount(link)

    def ensure_runtime_copy(self, link: HomeLink) -> bool:
        """Materialize one missing runtime file and report whether disk changed."""

        if isinstance(link, (HomeTopLink, HomeResourceLink)) and link.space == "memory":
            return False
        if isinstance(link, HomeTopLink):
            source = self._layout.source_for_top(link)
        elif isinstance(link, HomeResourceLink):
            source = self._layout.source_for_resource(link)
        else:
            source = self._layout.source_for_prompt_mount(link)
        runtime = self._layout.runtime_for_source(source)
        materialized = not runtime.is_file()
        self._overlay.ensure_copy(self._layout.relative_for_source(source))
        return materialized

    def write_resource(
        self,
        link: HomeResourceLink | str,
        text: str,
        *,
        overwrite: bool = False,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_resource_link(link)
        if not isinstance(text, str):
            raise AgentHomeContractError("Home write text must be a string")
        if len(text) > self._max_write_chars:
            raise AgentHomeContractError(
                f"Home write exceeds {self._max_write_chars} characters"
            )
        source = self._layout.source_for_resource(parsed)
        record = self._overlay.write(
            self._layout.relative_for_source(source),
            text,
            overwrite=overwrite,
            expected_digest=expected_digest,
        )
        return _mutation(str(parsed), record)

    def patch_resource(
        self,
        link: HomeResourceLink | str,
        *,
        old_text: str,
        new_text: str,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_resource_link(link)
        source = self._layout.source_for_resource(parsed)
        record = self._overlay.patch(
            self._layout.relative_for_source(source),
            old_text=old_text,
            new_text=new_text,
            expected_digest=expected_digest,
            max_chars=self._max_write_chars,
        )
        return _mutation(str(parsed), record)

    def delete_resource(
        self,
        link: HomeResourceLink | str,
        *,
        expected_digest: str = "",
    ) -> HomeResourceMutation:
        parsed = self._mutable_resource_link(link)
        source = self._layout.source_for_resource(parsed)
        record = self._overlay.delete(
            self._layout.relative_for_source(source),
            expected_digest=expected_digest,
        )
        return _mutation(str(parsed), record)

    def _runtime_read_path(self, link: str, source: Path) -> Path:
        relative = self._layout.relative_for_source(source)
        effective = self._overlay.effective(relative)
        if effective is None:
            if self._overlay.is_deleted(relative):
                raise AgentHomeContractError(
                    f"Home resource was deleted in the active day: {link}"
                )
            raise AgentHomeRuntimeCopyRequired(
                link,
                source_path=source,
                runtime_path=self._layout.runtime_for_source(source),
            )
        return effective.path

    def _read_optional_prompt_mount(self, link: HomePromptMountLink) -> str | None:
        source = self._layout.source_for_prompt_mount(link)
        relative = self._layout.relative_for_source(source)
        if not source.is_file() and self._overlay.effective(relative) is None:
            return None
        return _read_text(self._runtime_read_path(str(link), source))

    def _mutable_resource_link(
        self,
        link: HomeResourceLink | str,
    ) -> HomeResourceLink:
        parsed_link = parse_home_link(link) if isinstance(link, str) else link
        if not isinstance(parsed_link, HomeResourceLink):
            raise AgentHomeContractError(
                "Home mutation requires a progressive resource link"
            )
        if parsed_link.space == "memory":
            raise AgentHomeContractError(
                "Historical Home memory is read-only outside settlement"
            )
        if _is_top_entry_resource(parsed_link):
            raise AgentHomeContractError(
                "Top-level Home entries require a dedicated settlement action"
            )
        return parsed_link


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
            overlay=HomeOverlayManager(
                original_root=self._settings.original_root,
                runtime_root=self._settings.runtime_root,
            ),
            max_read_chars=self._settings.max_read_chars,
            max_write_chars=self._settings.max_write_chars,
        )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AgentHomeContractError(
            f"Agent Home file is not readable as UTF-8 text: {path}"
        ) from exc
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


def _file_digest(path: Path) -> str:
    from tinysoul.infra.filesystem import file_digest

    try:
        return file_digest(path)
    except OSError as exc:
        raise AgentHomeIOError(f"Failed to digest Agent Home file: {exc}") from exc


def _mutation(link: str, record: HomeOverlayRecord) -> HomeResourceMutation:
    return HomeResourceMutation(
        link=link,
        state=record.state,
        digest=record.runtime_digest,
        baseline_digest=record.baseline_digest,
        size=record.size,
    )


def _is_top_entry_resource(link: HomeResourceLink) -> bool:
    path = Path(link.relative_path)
    if link.space in {"agent", "what", "why", "memory"} and path.suffix.lower() == ".md":
        return True
    return link.space == "how" and path.name == "SKILL.md"
