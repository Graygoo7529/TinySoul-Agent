"""Strict metadata for general Agent Home skills."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import yaml

from ..errors import AgentHomeContractError
from ..refs import HomeTopRef

SKILL_FRONTMATTER_MAX_CHARS = 2048
SKILL_TITLE_MAX_CHARS = 160
SKILL_DESCRIPTION_MAX_CHARS = 320


@dataclass(frozen=True)
class HomeSkillMetadata:
    """Validated discovery metadata for one effective general skill."""

    ref: HomeTopRef
    title: str
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.ref, HomeTopRef) or self.ref.space != "skills":
            raise AgentHomeContractError("Skill metadata requires a general skill ref")
        _validate_field(
            self.title,
            name="title",
            max_chars=SKILL_TITLE_MAX_CHARS,
            ref=self.ref,
        )
        _validate_field(
            self.description,
            name="description",
            max_chars=SKILL_DESCRIPTION_MAX_CHARS,
            ref=self.ref,
        )

    @property
    def catalog_chars(self) -> int:
        return len(str(self.ref)) + len(self.title) + len(self.description) + 32


def parse_home_skill_metadata(text: str, *, ref: HomeTopRef) -> HomeSkillMetadata:
    """Parse the leading YAML frontmatter of a general skill SKILL.md."""

    if not isinstance(text, str):
        raise AgentHomeContractError(f"Skill frontmatter must be text: {ref}")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise AgentHomeContractError(
            f"Skill SKILL.md must start with YAML frontmatter: {ref}"
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
            f"Skill SKILL.md frontmatter exceeds {SKILL_FRONTMATTER_MAX_CHARS} "
            f"characters: {ref}"
        )
    if closing_index is None:
        raise AgentHomeContractError(f"Skill SKILL.md frontmatter is not closed: {ref}")
    frontmatter_chars = sum(len(line) for line in lines[: closing_index + 1])
    if frontmatter_chars > SKILL_FRONTMATTER_MAX_CHARS:
        raise AgentHomeContractError(
            f"Skill SKILL.md frontmatter exceeds {SKILL_FRONTMATTER_MAX_CHARS} "
            f"characters: {ref}"
        )
    source = "".join(lines[1:closing_index])
    try:
        value = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise AgentHomeContractError(
            f"Skill SKILL.md frontmatter is invalid YAML: {ref}"
        ) from exc
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise AgentHomeContractError(
            f"Skill SKILL.md frontmatter must be a string-keyed table: {ref}"
        )
    metadata = cast(Mapping[str, object], value)
    keys = set(metadata)
    if keys != {"title", "description"}:
        raise AgentHomeContractError(
            "Skill SKILL.md frontmatter must contain exactly title and description: "
            f"{ref}"
        )
    title = metadata["title"]
    description = metadata["description"]
    if not isinstance(title, str) or not isinstance(description, str):
        raise AgentHomeContractError(
            f"Skill SKILL.md title and description must be strings: {ref}"
        )
    return HomeSkillMetadata(
        ref=ref,
        title=title.strip(),
        description=description.strip(),
    )


def _validate_field(
    value: str,
    *,
    name: str,
    max_chars: int,
    ref: HomeTopRef,
) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AgentHomeContractError(f"Skill SKILL.md {name} must be non-empty: {ref}")
    if "\n" in value or "\r" in value:
        raise AgentHomeContractError(f"Skill SKILL.md {name} must be one line: {ref}")
    if len(value) > max_chars:
        raise AgentHomeContractError(
            f"Skill SKILL.md {name} exceeds {max_chars} characters: {ref}"
        )
