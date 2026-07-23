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
    """Raised when workspace filesystem operations fail at the module boundary."""


class WorkspaceReconciliationError(WorkspaceError):
    """Raised when disk inventory cannot be reconciled completely."""


class WorkspaceMirrorConflict(WorkspaceError):
    """Raised when active resources changed after a mirror baseline was taken."""


class WorkspaceTrashRestoreRequired(WorkspaceError):
    """Raised when an active resource can be recovered from Workspace Trash."""

    def __init__(self, *, link: str, trash_ref: str) -> None:
        super().__init__(f"Workspace resource requires Trash restore: {link}")
        self.link = link
        self.trash_ref = trash_ref


class WorkspaceSourceChanged(WorkspaceError):
    """Raised when an edit prompt source changed before commit."""

    def __init__(
        self,
        *,
        link: str,
        expected_state: str,
        actual_state: str,
        expected_digest: str = "",
        actual_digest: str = "",
    ) -> None:
        super().__init__(f"Workspace edit source changed before commit: {link}")
        self.link = link
        self.expected_state = expected_state
        self.actual_state = actual_state
        self.expected_digest = expected_digest
        self.actual_digest = actual_digest

