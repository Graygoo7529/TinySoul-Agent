"""Agent Home ref parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .errors import AgentHomeContractError, AgentHomeInvariantError

HOME_REF_PREFIX = "home:"
HOME_TOP_SPACES = frozenset({"agent", "skills"})
HOME_PROMPT_MOUNT_SPACES = frozenset({"skills_domain", "skills_action"})


@dataclass(frozen=True)
class HomeTopRef:
    """A top-level Agent Home background entry ref."""

    space: str
    name: str

    def __post_init__(self) -> None:
        _validate_space(self.space)
        if self.space in HOME_PROMPT_MOUNT_SPACES:
            raise AgentHomeInvariantError(
                "Automatic skill refs must use home:mount/domain/ or home:mount/action/"
            )
        if self.space not in HOME_TOP_SPACES:
            raise AgentHomeInvariantError(
                f"Unsupported Home top-level space: {self.space}"
            )
        _validate_relative_name(self.name, label="top name")
        path = PurePosixPath(self.name)
        if path.suffix:
            raise AgentHomeInvariantError(
                "Home top ref must use a logical name without a file suffix"
            )
        if self.space == "skills":
            if len(path.parts) != 1:
                raise AgentHomeInvariantError(
                    "Home skills top ref must use one skill name segment"
                )

    @classmethod
    def parse(cls, value: str) -> "HomeTopRef":
        body = _body(value)
        if not body.startswith("top/") or body.count("/") < 2:
            raise AgentHomeContractError(
                "Top Home ref must use home:top/<space>/<name>"
            )
        space, name = body.removeprefix("top/").split("/", 1)
        try:
            return cls(space=space, name=name)
        except AgentHomeInvariantError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def __str__(self) -> str:
        return f"{HOME_REF_PREFIX}top/{self.space}/{self.name}"


@dataclass(frozen=True)
class HomeResourceRef:
    """A progressive Agent Home resource ref."""

    space: str
    relative_path: str

    def __post_init__(self) -> None:
        _validate_space(self.space)
        if self.space in HOME_PROMPT_MOUNT_SPACES:
            raise AgentHomeInvariantError(
                "Automatic skill refs cannot be progressive resources"
            )
        if self.space not in HOME_TOP_SPACES:
            raise AgentHomeInvariantError(
                f"Unsupported Home resource space: {self.space}"
            )
        _validate_relative_name(self.relative_path, label="resource path")

    @classmethod
    def parse(cls, value: str) -> "HomeResourceRef":
        body = _body(value)
        if not body.startswith("resource/") or body.count("/") < 2:
            raise AgentHomeContractError(
                "Home resource ref must use home:resource/<space>/<path>"
            )
        space, relative = body.removeprefix("resource/").split("/", 1)
        try:
            return cls(space=space, relative_path=relative)
        except AgentHomeInvariantError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def __str__(self) -> str:
        return f"{HOME_REF_PREFIX}resource/{self.space}/{self.relative_path}"


@dataclass(frozen=True)
class HomePromptMountRef:
    """An automatic Agent Home prompt mount ref."""

    space: str
    name: str

    def __post_init__(self) -> None:
        if self.space not in HOME_PROMPT_MOUNT_SPACES:
            raise AgentHomeInvariantError(
                "Home prompt mount space must be skills_domain or skills_action"
            )
        _validate_relative_name(self.name, label="prompt mount name")
        parts = PurePosixPath(self.name).parts
        if self.space == "skills_domain" and len(parts) != 1:
            raise AgentHomeInvariantError(
                "Home domain skill mount ref must use one domain segment"
            )
        if self.space == "skills_action" and len(parts) != 2:
            raise AgentHomeInvariantError(
                "Home action skill mount ref must use <domain>/<action>"
            )

    @classmethod
    def parse(cls, value: str) -> "HomePromptMountRef":
        body = _body(value)
        if body.startswith("mount/domain/"):
            name = body[len("mount/domain/") :]
            space = "skills_domain"
        elif body.startswith("mount/action/"):
            name = body[len("mount/action/") :]
            space = "skills_action"
        else:
            raise AgentHomeContractError(
                "Home prompt mount ref must start with home:mount/domain/ "
                "or home:mount/action/"
            )
        try:
            return cls(space=space, name=name)
        except AgentHomeInvariantError as exc:
            raise AgentHomeContractError(str(exc)) from exc

    def __str__(self) -> str:
        category = "domain" if self.space == "skills_domain" else "action"
        return f"{HOME_REF_PREFIX}mount/{category}/{self.name}"


HomeRef = HomeTopRef | HomeResourceRef | HomePromptMountRef


def parse_home_ref(value: str) -> HomeRef:
    body = _body(value)
    if body.startswith("mount/"):
        return HomePromptMountRef.parse(value)
    if body.startswith("top/"):
        return HomeTopRef.parse(value)
    return HomeResourceRef.parse(value)


def _body(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(HOME_REF_PREFIX):
        raise AgentHomeContractError("Home ref must start with home:")
    body = value[len(HOME_REF_PREFIX) :]
    if not body:
        raise AgentHomeContractError("Home ref body must be non-empty")
    return body


def _validate_space(value: str) -> None:
    if not value or not value.replace("_", "").isalnum():
        raise AgentHomeInvariantError(
            "Home ref space must be alphanumeric or underscore"
        )


def _validate_relative_name(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise AgentHomeInvariantError(f"Home ref {label} must be non-empty")
    if "\\" in value:
        raise AgentHomeInvariantError(f"Home ref {label} must use POSIX separators")
    if value.startswith("/") or PurePosixPath(value).is_absolute():
        raise AgentHomeInvariantError(f"Home ref {label} must be relative")
    for part in value.split("/"):
        if part in {"", ".", ".."}:
            raise AgentHomeInvariantError(f"Home ref {label} has an invalid segment")
        if ":" in part:
            raise AgentHomeInvariantError(f"Home ref {label} cannot contain ':'")
