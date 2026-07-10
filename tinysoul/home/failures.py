"""Agent Home failures used by runtime bridge mapping."""

from __future__ import annotations

from enum import StrEnum


class AgentHomeFailureKind(StrEnum):
    """Stable Agent Home failure kinds that can cross into Runtime."""

    CONFIGURATION_FAILED = "home.configuration_failed"
    CONTRACT_VIOLATION = "home.contract_violation"
    IO_FAILED = "home.io_failed"
    RUNTIME_COPY_REQUIRED = "home.runtime_copy_required"
    INTERNAL_FAILURE = "home.internal_failure"
