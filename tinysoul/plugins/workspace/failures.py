"""Workspace failures used by runtime bridge mapping."""

from __future__ import annotations

from enum import StrEnum


class WorkspaceFailureKind(StrEnum):
    """Stable workspace failure kinds that can cross into Runtime."""

    CONFIGURATION_FAILED = "workspace.configuration_failed"
    CONTRACT_VIOLATION = "workspace.contract_violation"
    IO_FAILED = "workspace.io_failed"
    INTERNAL_FAILURE = "workspace.internal_failure"
