"""Workspace module errors."""

from __future__ import annotations


class WorkspaceError(Exception):
    """Base class for workspace module errors."""


class WorkspaceContractError(WorkspaceError):
    """Raised when callers violate the workspace module contract."""


class WorkspaceInvariantError(WorkspaceError):
    """Raised when workspace internal invariants are broken."""


class WorkspaceIOError(WorkspaceError):
    """Raised when workspace filesystem operations fail at the module boundary."""


class WorkspaceReconciliationError(WorkspaceError):
    """Raised when disk inventory cannot be reconciled completely."""

