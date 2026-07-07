"""Agent Home link parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .errors import AgentHomeContractError, AgentHomeInvariantError

HOME_LINK_PREFIX = "home:"


@dataclass(frozen=True)
class HomeTopLink:
    """A top-level Agent Home link loadable into BackgroundContext."""

    space: str
    name: str

    def __post_init__(self) -> None:
        _validate_space(self.space)
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


HomeLink = HomeTopLink | HomeResourceLink


def parse_home_link(value: str) -> HomeLink:
    body = _body(value)
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
