"""Infra module failure semantics."""

from __future__ import annotations

from enum import StrEnum


class InfraFailureKind(StrEnum):
    """Stable infra failure kinds used by runtime bridges."""

    # Bridge-mapped failures.
    CONFIGURATION_FAILED = "infra.configuration_failed"
    JSON_BOUNDARY_FAILED = "infra.json_boundary_failed"
    CONTRACT_VIOLATION = "infra.contract_violation"
    INTERNAL_FAILURE = "infra.internal_failure"
