"""Infra module failure semantics."""

from __future__ import annotations

from enum import StrEnum


class InfraFailureKind(StrEnum):
    """Stable infra failure kinds used by runtime bridges."""

    CONFIGURATION_FAILED = "infra.configuration_failed"
