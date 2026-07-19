"""Stable Script failures that may cross into Runtime."""

from __future__ import annotations

from enum import StrEnum


class ScriptFailureKind(StrEnum):
    """Script failure kinds reserved for non-Action runtime boundaries."""

    CONFIGURATION_FAILED = "script.configuration_failed"
    CONTRACT_VIOLATION = "script.contract_violation"
    INTERNAL_FAILURE = "script.internal_failure"
