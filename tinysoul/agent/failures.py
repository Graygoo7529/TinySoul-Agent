"""App failure kinds used by the runtime bridge."""

from __future__ import annotations

from enum import StrEnum


class AgentFailureKind(StrEnum):
    """Stable app failures that need runtime-level control flow."""

    CONFIGURATION_FAILED = "agent.configuration_failed"
    CONTRACT_VIOLATION = "agent.contract_violation"
    INTERNAL_FAILURE = "agent.internal_failure"
