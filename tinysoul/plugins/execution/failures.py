"""Execution request failures are distinct from Job supervision failures."""

from enum import StrEnum


class ExecutionFailureKind(StrEnum):
    CONFIGURATION_FAILED = "execution.configuration_failed"


class ExecutionRequestError(Exception):
    """The caller can correct this bounded execution request."""


class ExecutionStartError(Exception):
    """The requested process could not start; no live handle was accepted."""
