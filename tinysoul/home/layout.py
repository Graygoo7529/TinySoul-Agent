"""Agent Home filesystem layout mapping."""

from __future__ import annotations

from pathlib import Path

from tinysoul.infra.filesystem import FilesystemBoundaryError, resolve_under_root

from .config import AgentHomeSettings
from .errors import AgentHomeContractError, AgentHomeInvariantError
from .links import HomePromptMountLink, HomeResourceLink, HomeTopLink


class AgentHomeLayout:
    """Map Agent Home links to source and runtime paths."""

    def __init__(self, settings: AgentHomeSettings) -> None:
        self._settings = settings
        self._content_root = settings.original_root

    @property
    def settings(self) -> AgentHomeSettings:
        return self._settings

    @property
    def content_root(self) -> Path:
        return self._content_root

    def source_for_top(self, link: HomeTopLink) -> Path:
        candidates = self._top_candidates(link)
        existing = tuple(path for path in candidates if path.is_file())
        if len(existing) > 1:
            raise AgentHomeInvariantError(
                f"Home top-level link has multiple source files: {link}"
            )
        if existing:
            return existing[0]
        return candidates[0]

    def source_for_resource(self, link: HomeResourceLink) -> Path:
        return self._under_content_root(link.space, link.relative_path)

    def source_for_prompt_mount(self, link: HomePromptMountLink) -> Path:
        if link.space == "how_domain":
            return self._under_content_root("how_domain", link.name, "DOMAIN.md")
        return self._under_content_root("how_action", f"{link.name}.md")

    def runtime_for_source(self, source: Path) -> Path:
        relative = self.relative_for_source(source)
        try:
            return resolve_under_root(
                self._settings.runtime_root,
                relative,
            )
        except FilesystemBoundaryError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def relative_for_source(self, source: Path) -> str:
        source_resolved = source.resolve()
        try:
            relative = source_resolved.relative_to(self._content_root.resolve())
        except ValueError:
            raise AgentHomeContractError("Home source path is outside content root")
        return relative.as_posix()

    def is_top_source(self, source: Path) -> bool:
        relative = self.relative_for_source(source)
        return any(
            self.relative_for_source(self.source_for_top(link)) == relative
            for link in self.top_links()
        )

    def top_links(self) -> tuple[HomeTopLink, ...]:
        links: list[HomeTopLink] = []
        core = HomeTopLink("agent", "core")
        if self.source_for_top(core).is_file():
            links.append(core)
        links.extend(self._agent_links())
        links.extend(self._what_links())
        links.extend(self._simple_space_links("why"))
        links.extend(self._package_links("how", "SKILL.md"))
        links.extend(self._simple_space_links("memory"))
        return _dedupe_links(tuple(links))

    def _top_candidates(self, link: HomeTopLink) -> tuple[Path, ...]:
        if link.space == "agent" and link.name == "core":
            return (self._content_root / "agent" / "AGENT.md",)
        if link.space == "agent":
            return (self._under_content_root("agent", f"{link.name}.md"),)
        if link.space == "how":
            return (self._under_content_root("how", link.name, "SKILL.md"),)
        if link.space == "what":
            return (
                self._under_content_root("what", f"{link.name}.md"),
                self._under_content_root("what", "entity", f"{link.name}.md"),
                self._under_content_root("what", "concept", f"{link.name}.md"),
            )
        if link.space == "why":
            return (self._under_content_root("why", f"{link.name}.md"),)
        if link.space == "memory":
            return (self._under_content_root("memory", f"{link.name}.md"),)
        return (self._under_content_root(link.space, f"{link.name}.md"),)

    def _under_content_root(self, *parts: str) -> Path:
        relative = "/".join(parts)
        try:
            return resolve_under_root(self._content_root, relative)
        except FilesystemBoundaryError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def _agent_links(self) -> tuple[HomeTopLink, ...]:
        root = self._content_root / "agent"
        if not root.is_dir():
            return ()
        result: list[HomeTopLink] = []
        for path in sorted(root.rglob("*.md"), key=lambda item: item.as_posix()):
            if path.name == "AGENT.md":
                continue
            relative = path.relative_to(root).with_suffix("").as_posix()
            result.append(HomeTopLink("agent", relative))
        return tuple(result)

    def _what_links(self) -> tuple[HomeTopLink, ...]:
        root = self._content_root / "what"
        if not root.is_dir():
            return ()
        result: list[HomeTopLink] = []
        for path in sorted(root.rglob("*.md"), key=lambda item: item.as_posix()):
            relative = path.relative_to(root).with_suffix("")
            parts = relative.parts
            if len(parts) > 1 and parts[0] in {"entity", "concept"}:
                relative = Path(*parts[1:])
            result.append(HomeTopLink("what", relative.as_posix()))
        return tuple(result)

    def _simple_space_links(self, space: str) -> tuple[HomeTopLink, ...]:
        root = self._content_root / space
        if not root.is_dir():
            return ()
        result: list[HomeTopLink] = []
        for path in sorted(root.rglob("*.md"), key=lambda item: item.as_posix()):
            relative = path.relative_to(root).with_suffix("").as_posix()
            result.append(HomeTopLink(space, relative))
        return tuple(result)

    def _package_links(self, space: str, entry_name: str) -> tuple[HomeTopLink, ...]:
        root = self._content_root / space
        if not root.is_dir():
            return ()
        result: list[HomeTopLink] = []
        for package in sorted(root.iterdir(), key=lambda item: item.name):
            if not package.is_dir():
                continue
            if (package / entry_name).is_file():
                result.append(HomeTopLink(space, package.name))
        return tuple(result)


def _dedupe_links(links: tuple[HomeTopLink, ...]) -> tuple[HomeTopLink, ...]:
    seen: set[str] = set()
    result: list[HomeTopLink] = []
    for link in links:
        text = str(link)
        if text in seen:
            raise AgentHomeInvariantError(
                f"Agent Home contains duplicate top-level link: {text}"
            )
        seen.add(text)
        result.append(link)
    return tuple(result)
