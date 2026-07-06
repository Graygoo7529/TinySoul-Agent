"""Context module failure semantics."""

from __future__ import annotations

from enum import StrEnum


class ContextFailureKind(StrEnum):
    """Stable context failure kinds used by runtime bridges."""

    CONFIGURATION_FAILED = "context.configuration_failed"
    CONTRACT_VIOLATION = "context.contract_violation"
    INTERNAL_FAILURE = "context.internal_failure"
    BUDGET_EXCEEDED = "context.budget_exceeded"
