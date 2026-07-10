"""Loop failure kinds used by the runtime bridge."""

from __future__ import annotations

from enum import StrEnum


class LoopFailureKind(StrEnum):
    """Stable loop failures that need runtime-level control flow."""

    CONFIGURATION_FAILED = "loop.configuration_failed"
    CONTRACT_VIOLATION = "loop.contract_violation"
    INTERNAL_FAILURE = "loop.internal_failure"
