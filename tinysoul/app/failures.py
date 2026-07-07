"""App failure kinds used by the runtime bridge."""

from __future__ import annotations

from enum import StrEnum


class AppFailureKind(StrEnum):
    """Stable app failures that need runtime-level control flow."""

    CONFIGURATION_FAILED = "configuration_failed"
    CONTRACT_VIOLATION = "contract_violation"
    INTERNAL_FAILURE = "internal_failure"
