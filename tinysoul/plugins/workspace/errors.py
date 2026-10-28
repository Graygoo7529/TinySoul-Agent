"""Workspace module errors."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject


class WorkspaceError(Exception):
    """Base class for workspace module errors."""


class WorkspaceContractError(WorkspaceError):
    """Raised when callers violate the workspace module contract."""

    def __init__(self, message: str, *, feedback: str = "") -> None:
        super().__init__(message)
        self.feedback = feedback


class WorkspacePromptReferenceError(WorkspaceContractError):
    """A task source cannot be used; feedback is safe for the local Action result."""

    def __init__(
        self,
        feedback: str,
        *,
        reason: str,
        payload: JsonObject | None = None,
    ) -> None:
        super().__init__(feedback, feedback=feedback)
        self.reason = reason
        self.payload = payload or {}


class WorkspaceImageValidationError(WorkspaceContractError):
    """Raised when image bytes do not match the classified media type."""


class WorkspaceNotFoundError(WorkspaceContractError):
    """Requested Workspace resource is absent from its day."""


class WorkspaceInvariantError(WorkspaceError):
    """Raised when workspace internal invariants are broken."""


class WorkspaceIOError(WorkspaceError):
    """Filesystem failure, preserving known committed side effects."""

    def __init__(self, message: str, *, committed_refs: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.committed_refs = committed_refs


class WorkspaceReconciliationError(WorkspaceError):
    """Raised when disk inventory cannot be reconciled completely."""
