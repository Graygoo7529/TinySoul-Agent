"""Agent Home link parsing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from .errors import AgentHomeContractError, AgentHomeInvariantError

HOME_LINK_PREFIX = "home:"
HOME_TOP_SPACES = frozenset({"agent", "what", "why", "how"})


class HomeWhatKind(StrEnum):
    """Physical classification required when creating a WHAT entry."""

    ENTITY = "entity"
    CONCEPT = "concept"


@dataclass(frozen=True)
class HomeTopLink:
    """A top-level Agent Home background entry link."""

    space: str
    name: str

    def __post_init__(self) -> None:
        _validate_space(self.space)
        if self.space in {"how_domain", "how_action"}:
            raise AgentHomeInvariantError(
                "Automatic HOW links must use home:how_domain: or home:how_action:"
            )
        if self.space not in HOME_TOP_SPACES:
            raise AgentHomeInvariantError(
                f"Unsupported Home top-level space: {self.space}"
            )
        _validate_relative_name(self.name, label="top name")

    @classmethod
    def parse(cls, value: str) -> "HomeTopLink":
        body = _body(value)
        if "@" not in body:
            raise AgentHomeContractError("Top-level home link must contain @")
        space, name = body.split("@", 1)
        try:
            return cls(space=space, name=name)
        except AgentHomeInvariantError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def __str__(self) -> str:
        return f"{HOME_LINK_PREFIX}{self.space}@{self.name}"


@dataclass(frozen=True)
class HomeResourceLink:
    """A progressive Agent Home resource link."""

    space: str
    relative_path: str

    def __post_init__(self) -> None:
        _validate_space(self.space)
        if self.space in {"how_domain", "how_action"}:
            raise AgentHomeInvariantError(
                "Automatic HOW links cannot be progressive resources"
            )
        if self.space not in HOME_TOP_SPACES:
            raise AgentHomeInvariantError(
                f"Unsupported Home resource space: {self.space}"
            )
        _validate_relative_name(self.relative_path, label="resource path")

    @classmethod
    def parse(cls, value: str) -> "HomeResourceLink":
        body = _body(value)
        if "@" in body:
            raise AgentHomeContractError("Resource home link cannot contain @")
        if "/" not in body:
            raise AgentHomeContractError("Resource home link must contain /")
        space, relative = body.split("/", 1)
        try:
            return cls(space=space, relative_path=relative)
        except AgentHomeInvariantError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def __str__(self) -> str:
        return f"{HOME_LINK_PREFIX}{self.space}/{self.relative_path}"


@dataclass(frozen=True)
class HomePromptMountLink:
    """An automatic Agent Home prompt mount link."""

    space: str
    name: str

    def __post_init__(self) -> None:
        if self.space not in {"how_domain", "how_action"}:
            raise AgentHomeInvariantError(
                "Home prompt mount space must be how_domain or how_action"
            )
        _validate_relative_name(self.name, label="prompt mount name")
        parts = PurePosixPath(self.name).parts
        if self.space == "how_domain" and len(parts) != 1:
            raise AgentHomeInvariantError(
                "Home domain HOW mount link must use one domain segment"
            )
        if self.space == "how_action" and len(parts) != 2:
            raise AgentHomeInvariantError(
                "Home action HOW mount link must use <domain>/<action>"
            )

    @classmethod
    def parse(cls, value: str) -> "HomePromptMountLink":
        body = _body(value)
        if body.startswith("how_domain:"):
            name = body[len("how_domain:") :]
            space = "how_domain"
        elif body.startswith("how_action:"):
            name = body[len("how_action:") :]
            space = "how_action"
        else:
            raise AgentHomeContractError(
                "Home prompt mount link must start with home:how_domain: "
                "or home:how_action:"
            )
        try:
            return cls(space=space, name=name)
        except AgentHomeInvariantError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def __str__(self) -> str:
        return f"{HOME_LINK_PREFIX}{self.space}:{self.name}"


HomeLink = HomeTopLink | HomeResourceLink | HomePromptMountLink


def parse_home_link(value: str) -> HomeLink:
    body = _body(value)
    if body.startswith("how_domain:") or body.startswith("how_action:"):
        return HomePromptMountLink.parse(value)
    if "@" in body:
        return HomeTopLink.parse(value)
    return HomeResourceLink.parse(value)


def _body(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(HOME_LINK_PREFIX):
        raise AgentHomeContractError("Home link must start with home:")
    body = value[len(HOME_LINK_PREFIX) :]
    if not body:
        raise AgentHomeContractError("Home link body must be non-empty")
    return body


def _validate_space(value: str) -> None:
    if not value or not value.replace("_", "").isalnum():
        raise AgentHomeInvariantError("Home link space must be alphanumeric or underscore")


def _validate_relative_name(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise AgentHomeInvariantError(f"Home link {label} must be non-empty")
    if "\\" in value:
        raise AgentHomeInvariantError(f"Home link {label} must use POSIX separators")
    if value.startswith("/") or PurePosixPath(value).is_absolute():
        raise AgentHomeInvariantError(f"Home link {label} must be relative")
    for part in PurePosixPath(value).parts:
        if part in {"", ".", ".."}:
            raise AgentHomeInvariantError(f"Home link {label} has an invalid segment")
        if ":" in part:
            raise AgentHomeInvariantError(f"Home link {label} cannot contain ':'")
