"""Action module failure semantics."""

from __future__ import annotations

from enum import StrEnum


class ActionFailureKind(StrEnum):
    """Stable action failure kinds used by runtime bridges."""

    CONFIGURATION_FAILED = "action.configuration_failed"
    CONTRACT_VIOLATION = "action.contract_violation"
    INTERNAL_FAILURE = "action.internal_failure"
