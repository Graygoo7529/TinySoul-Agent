"""Strict metadata for general Agent Home HOW skills."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import yaml

from .errors import AgentHomeContractError
from .links import HomeTopLink


SKILL_FRONTMATTER_MAX_CHARS = 2048
SKILL_TITLE_MAX_CHARS = 160
SKILL_DESCRIPTION_MAX_CHARS = 320


@dataclass(frozen=True)
class HomeSkillMetadata:
    """Validated discovery metadata for one effective general HOW skill."""

    link: HomeTopLink
    title: str
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.link, HomeTopLink) or self.link.space != "how":
            raise AgentHomeContractError("Skill metadata requires a general HOW link")
        _validate_field(
            self.title,
            name="title",
            max_chars=SKILL_TITLE_MAX_CHARS,
            link=self.link,
        )
        _validate_field(
            self.description,
            name="description",
            max_chars=SKILL_DESCRIPTION_MAX_CHARS,
            link=self.link,
        )

    @property
    def catalog_chars(self) -> int:
        return len(str(self.link)) + len(self.title) + len(self.description) + 32


def parse_home_skill_metadata(text: str, *, link: HomeTopLink) -> HomeSkillMetadata:
    """Parse the leading YAML frontmatter of a general HOW SKILL.md."""

    if not isinstance(text, str):
        raise AgentHomeContractError(f"HOW frontmatter must be text: {link}")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise AgentHomeContractError(
            f"HOW SKILL.md must start with YAML frontmatter: {link}"
        )
    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip("\r\n") == "---"
        ),
        None,
    )
    if closing_index is None and len(text) > SKILL_FRONTMATTER_MAX_CHARS:
        raise AgentHomeContractError(
            f"HOW SKILL.md frontmatter exceeds {SKILL_FRONTMATTER_MAX_CHARS} "
            f"characters: {link}"
        )
    if closing_index is None:
        raise AgentHomeContractError(
            f"HOW SKILL.md frontmatter is not closed: {link}"
        )
    frontmatter_chars = sum(len(line) for line in lines[: closing_index + 1])
    if frontmatter_chars > SKILL_FRONTMATTER_MAX_CHARS:
        raise AgentHomeContractError(
            f"HOW SKILL.md frontmatter exceeds {SKILL_FRONTMATTER_MAX_CHARS} "
            f"characters: {link}"
        )
    source = "".join(lines[1:closing_index])
    try:
        value = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise AgentHomeContractError(
            f"HOW SKILL.md frontmatter is invalid YAML: {link}"
        ) from exc
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise AgentHomeContractError(
            f"HOW SKILL.md frontmatter must be a string-keyed table: {link}"
        )
    metadata = cast(Mapping[str, object], value)
    keys = set(metadata)
    if keys != {"title", "description"}:
        raise AgentHomeContractError(
            "HOW SKILL.md frontmatter must contain exactly title and description: "
            f"{link}"
        )
    title = metadata["title"]
    description = metadata["description"]
    if not isinstance(title, str) or not isinstance(description, str):
        raise AgentHomeContractError(
            f"HOW SKILL.md title and description must be strings: {link}"
        )
    return HomeSkillMetadata(
        link=link,
        title=title.strip(),
        description=description.strip(),
    )


def _validate_field(
    value: str,
    *,
    name: str,
    max_chars: int,
    link: HomeTopLink,
) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AgentHomeContractError(
            f"HOW SKILL.md {name} must be non-empty: {link}"
        )
    if "\n" in value or "\r" in value:
        raise AgentHomeContractError(
            f"HOW SKILL.md {name} must be one line: {link}"
        )
    if len(value) > max_chars:
        raise AgentHomeContractError(
            f"HOW SKILL.md {name} exceeds {max_chars} characters: {link}"
        )
