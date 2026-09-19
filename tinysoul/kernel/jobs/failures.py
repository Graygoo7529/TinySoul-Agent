"""Stable failures of Job supervision and resource ownership."""

from enum import StrEnum


class JobFailureKind(StrEnum):
    CONFIGURATION_FAILED = "jobs.configuration_failed"
    CONTRACT_VIOLATION = "jobs.contract_violation"
    SUPERVISION_FAILED = "jobs.supervision_failed"
    EXECUTION_CLOSE_FAILED = "jobs.execution_close_failed"


class JobError(Exception):
    """The Job owner cannot satisfy its supervision contract."""

    def __init__(
        self, message: str, *, kind: JobFailureKind = JobFailureKind.CONTRACT_VIOLATION
    ) -> None:
        super().__init__(message)
        self.kind = kind


class JobRequestError(JobError):
    """A caller can correct a Job identity or admission request."""
