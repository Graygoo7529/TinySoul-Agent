"""Workspace module errors."""

from __future__ import annotations


class WorkspaceError(Exception):
    """Base class for workspace module errors."""


class WorkspaceContractError(WorkspaceError):
    """Raised when callers violate the workspace module contract."""


class WorkspaceImageValidationError(WorkspaceContractError):
    """Raised when image bytes do not match the classified media type."""


class WorkspaceInvariantError(WorkspaceError):
    """Raised when workspace internal invariants are broken."""


class WorkspaceIOError(WorkspaceError):
    """Filesystem failure, preserving known committed side effects."""

    def __init__(self, message: str, *, committed_links: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.committed_links = committed_links


class WorkspaceReconciliationError(WorkspaceError):
    """Raised when disk inventory cannot be reconciled completely."""
