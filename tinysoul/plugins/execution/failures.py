"""Execution request failures are distinct from Job supervision failures."""

from enum import StrEnum


class ExecutionFailureKind(StrEnum):
    CONFIGURATION_FAILED = "execution.configuration_failed"


class ExecutionRequestError(Exception):
    """The caller can correct this bounded execution request."""

    def __init__(self, feedback: str) -> None:
        bounded_feedback = feedback[:240]
        super().__init__(bounded_feedback)
        self.feedback = bounded_feedback


class ExecutionStartError(Exception):
    """The requested process could not start; no live handle was accepted."""
