"""Stable Reflection failures exposed to Runtime."""

from __future__ import annotations

from enum import StrEnum


class ReflectionFailureKind(StrEnum):
    CONFIGURATION_FAILED = "reflection.configuration_failed"
    CONTRACT_VIOLATION = "reflection.contract_violation"
    INVARIANT_VIOLATION = "reflection.invariant_violation"
