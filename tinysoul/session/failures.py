"""Stable Session failure kinds used by Runtime bridge."""

from enum import StrEnum


class SessionFailureKind(StrEnum):
    CONFIGURATION_FAILED = "session.configuration_failed"
    IO_FAILED = "session.io_failed"
    CONTRACT_VIOLATION = "session.contract_violation"
    INTERNAL_FAILURE = "session.internal_failure"
