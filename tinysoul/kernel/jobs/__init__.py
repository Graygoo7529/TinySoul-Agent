"""Turn-owned external work, independent of execution backends."""

from .models import (
    JobBackend,
    JobControl,
    JobInputKind,
    JobInputOption,
    JobInputRequest,
    JobSnapshot,
    JobState,
)
from .registry import JobRegistry
from .failures import JobError, JobRequestError, JobFailureKind
from .segment import jobs_segment_registration

__all__ = [
    "JobBackend",
    "JobControl",
    "JobInputKind",
    "JobInputOption",
    "JobInputRequest",
    "JobError",
    "JobRequestError",
    "JobFailureKind",
    "JobRegistry",
    "JobSnapshot",
    "JobState",
    "jobs_segment_registration",
]
