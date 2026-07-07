"""Workspace link parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .errors import WorkspaceContractError, WorkspaceInvariantError

WORKSPACE_LINK_PREFIX = "workspace:"


@dataclass(frozen=True)
class WorkspaceLink:
    """A validated workspace resource link."""

    relative_path: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path)

    @classmethod
    def parse(cls, value: str) -> "WorkspaceLink":
        if not value.startswith(WORKSPACE_LINK_PREFIX):
            raise WorkspaceContractError("Workspace link must start with workspace:")
        try:
            return cls(value[len(WORKSPACE_LINK_PREFIX) :])
        except WorkspaceInvariantError as exc:
            raise WorkspaceContractError(str(exc)) from exc

    @classmethod
    def from_relative_path(cls, value: str) -> "WorkspaceLink":
        return cls(value)

    @property
    def path(self) -> PurePosixPath:
        return PurePosixPath(self.relative_path)

    def __str__(self) -> str:
        return f"{WORKSPACE_LINK_PREFIX}{self.relative_path}"


def _validate_relative_path(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise WorkspaceInvariantError("Workspace link path must be non-empty")
    if "\\" in value:
        raise WorkspaceInvariantError("Workspace link path must use POSIX separators")
    if value.startswith("/") or PurePosixPath(value).is_absolute():
        raise WorkspaceInvariantError("Workspace link path must be relative")
    parts = PurePosixPath(value).parts
    for part in parts:
        if part in {"", ".", ".."}:
            raise WorkspaceInvariantError("Workspace link path contains an invalid segment")
        if ":" in part:
            raise WorkspaceInvariantError("Workspace link path cannot contain ':'")
