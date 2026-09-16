"""Memory failures used by Runtime bridge mapping."""

from __future__ import annotations

from enum import StrEnum


class MemoryFailureKind(StrEnum):
    """Stable Memory failure kinds that can cross into Runtime."""

    CONFIGURATION_FAILED = "memory.configuration_failed"
    CONTRACT_VIOLATION = "memory.contract_violation"
    IO_FAILED = "memory.io_failed"
    INTERNAL_FAILURE = "memory.internal_failure"
