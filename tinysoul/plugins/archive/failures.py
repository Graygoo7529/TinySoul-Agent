"""Stable Archive lifecycle failures crossing into Runtime."""

from enum import StrEnum


class ArchiveFailureKind(StrEnum):
    PREPARATION_FAILED = "archive.preparation_failed"
    CONTRACT_VIOLATION = "archive.contract_violation"
    INVARIANT_VIOLATION = "archive.invariant_violation"
