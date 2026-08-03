"""Stable Maintenance failures exposed to Runtime."""

from __future__ import annotations

from enum import StrEnum


class MaintenanceFailureKind(StrEnum):
    CONFIGURATION_FAILED = "maintenance.configuration_failed"
    CONTRACT_VIOLATION = "maintenance.contract_violation"
    INVARIANT_VIOLATION = "maintenance.invariant_violation"
