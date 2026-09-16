"""Stable supervised process failures that may cross into Runtime."""

from enum import StrEnum


class SupervisedProcessFailureKind(StrEnum):
    CONFIGURATION_FAILED = "supervised_process.configuration_failed"
    CONTRACT_VIOLATION = "supervised_process.contract_violation"
    EXECUTION_FAILED = "supervised_process.execution_failed"
    INTERNAL_FAILURE = "supervised_process.internal_failure"
