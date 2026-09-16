"""Agent Home filesystem layout mapping."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

from tinysoul.infra.filesystem import FilesystemBoundaryError, resolve_under_root

from .config import AgentHomeSettings
from .errors import AgentHomeContractError, AgentHomeInvariantError
from .links import (
    HomeLink,
    HomePromptMountLink,
    HomeResourceLink,
    HomeTopLink,
)


class AgentHomeLayout:
    """Map stable Home links to actual/runtime relative paths."""

    def __init__(self, settings: AgentHomeSettings) -> None:
        self._settings = settings
        self._content_root = settings.original_root

    @property
    def settings(self) -> AgentHomeSettings:
        return self._settings

    @property
    def content_root(self) -> Path:
        return self._content_root

    def relative_for_top(self, link: HomeTopLink) -> str:
        if link.space == "agent":
            return f"agent/{link.name}.md"
        if link.space == "skills":
            _require_single_segment(link.name, label="Home skill name")
            return f"skills/{link.name}/SKILL.md"
        raise AgentHomeInvariantError(f"Unsupported Home top space: {link.space}")

    def relative_for_resource(self, link: HomeResourceLink) -> str:
        return f"{link.space}/{link.relative_path}"

    def relative_for_prompt_mount(self, link: HomePromptMountLink) -> str:
        if link.space == "skills_domain":
            return f"skills_domain/{link.name}/DOMAIN.md"
        return f"skills_action/{link.name}.md"

    def source_for_relative(self, relative_path: str) -> Path:
        return self._under_content_root(relative_path)

    def source_for_resource(self, link: HomeResourceLink) -> Path:
        return self.source_for_relative(self.relative_for_resource(link))

    def source_for_prompt_mount(self, link: HomePromptMountLink) -> Path:
        return self.source_for_relative(self.relative_for_prompt_mount(link))

    def runtime_for_relative(self, relative_path: str) -> Path:
        try:
            return resolve_under_root(self._settings.runtime_root, relative_path)
        except FilesystemBoundaryError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def runtime_for_source(self, source: Path) -> Path:
        return self.runtime_for_relative(self.relative_for_source(source))

    def relative_for_source(self, source: Path) -> str:
        source_resolved = source.resolve()
        try:
            relative = source_resolved.relative_to(self._content_root.resolve())
        except ValueError:
            raise AgentHomeContractError("Home source path is outside content root")
        return relative.as_posix()

    def actual_top_relatives(self) -> tuple[str, ...]:
        return self._actual_relatives(self.top_link_for_relative)

    def actual_prompt_mount_relatives(self) -> tuple[str, ...]:
        return self._actual_relatives(self.prompt_mount_link_for_relative)

    def top_link_for_relative(self, relative_path: str) -> HomeTopLink | None:
        path = PurePosixPath(relative_path)
        parts = path.parts
        if path.suffix != ".md" or not parts:
            return None
        if len(parts) >= 2 and parts[0] == "agent":
            name = _without_markdown_suffix(PurePosixPath(*parts[1:]))
            return HomeTopLink("agent", name)
        if len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL.md":
            return HomeTopLink("skills", parts[1])
        return None

    def prompt_mount_link_for_relative(
        self,
        relative_path: str,
    ) -> HomePromptMountLink | None:
        parts = PurePosixPath(relative_path).parts
        if (
            len(parts) == 3
            and parts[0] == "skills_domain"
            and parts[2] == "DOMAIN.md"
        ):
            return HomePromptMountLink("skills_domain", parts[1])
        if (
            len(parts) == 3
            and parts[0] == "skills_action"
            and parts[2].endswith(".md")
        ):
            return HomePromptMountLink(
                "skills_action",
                f"{parts[1]}/{PurePosixPath(parts[2]).stem}",
            )
        return None

    def link_for_relative(self, relative_path: str) -> HomeLink | None:
        top = self.top_link_for_relative(relative_path)
        if top is not None:
            return top
        prompt_mount = self.prompt_mount_link_for_relative(relative_path)
        if prompt_mount is not None:
            return prompt_mount
        parts = PurePosixPath(relative_path).parts
        if len(parts) < 2 or parts[0] in {
            ".tinysoul",
            "skills_domain",
            "skills_action",
        }:
            return None
        return HomeResourceLink(parts[0], PurePosixPath(*parts[1:]).as_posix())

    def _actual_relatives(
        self,
        mapper: Callable[
            [str],
            HomeTopLink | HomePromptMountLink | None,
        ],
    ) -> tuple[str, ...]:
        if not self._content_root.is_dir():
            return ()
        result: list[str] = []
        for path in sorted(
            self._content_root.rglob("*.md"),
            key=lambda item: item.as_posix(),
        ):
            relative = path.relative_to(self._content_root).as_posix()
            if path.is_symlink():
                raise AgentHomeInvariantError(
                    f"Actual Home cannot contain symlink content: {relative}"
                )
            if not path.is_file():
                continue
            link = mapper(relative)
            if link is not None:
                result.append(relative)
        return tuple(result)

    def _under_content_root(self, *parts: str) -> Path:
        relative = "/".join(parts)
        try:
            return resolve_under_root(self._content_root, relative)
        except FilesystemBoundaryError as exc:
            raise AgentHomeContractError(str(exc)) from exc


def _require_single_segment(value: str, *, label: str) -> None:
    if len(PurePosixPath(value).parts) != 1:
        raise AgentHomeContractError(f"{label} must use one path segment")


def _without_markdown_suffix(value: PurePosixPath) -> str:
    if value.suffix != ".md":
        raise AgentHomeInvariantError("Home top file must use the .md suffix")
    return value.with_suffix("").as_posix()
