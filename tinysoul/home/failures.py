"""Agent Home failures used by runtime bridge mapping."""

from __future__ import annotations

from enum import StrEnum


class AgentHomeFailureKind(StrEnum):
    """Stable Agent Home failure kinds that can cross into Runtime."""

    CONFIGURATION_FAILED = "configuration_failed"
    CONTRACT_VIOLATION = "contract_violation"
    IO_FAILED = "io_failed"
    RUNTIME_COPY_REQUIRED = "runtime_copy_required"
    INTERNAL_FAILURE = "internal_failure"
