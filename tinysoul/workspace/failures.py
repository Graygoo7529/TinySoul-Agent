"""Workspace failures used by runtime bridge mapping."""

from __future__ import annotations

from enum import StrEnum


class WorkspaceFailureKind(StrEnum):
    """Stable workspace failure kinds that can cross into Runtime."""

    CONFIGURATION_FAILED = "configuration_failed"
    CONTRACT_VIOLATION = "contract_violation"
    IO_FAILED = "io_failed"
    INTERNAL_FAILURE = "internal_failure"
