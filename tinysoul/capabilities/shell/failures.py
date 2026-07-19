"""Stable Shell failures that may cross into Runtime."""

from enum import StrEnum


class ShellFailureKind(StrEnum):
    CONFIGURATION_FAILED = "shell.configuration_failed"
    CONTRACT_VIOLATION = "shell.contract_violation"
    INTERNAL_FAILURE = "shell.internal_failure"
