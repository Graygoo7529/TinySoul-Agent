"""Turn-owned external work, independent of execution backends."""

from .registry import JobBackend, JobError, JobRegistry, JobSnapshot, JobState
from .segment import jobs_segment_registration

__all__ = ["JobBackend", "JobError", "JobRegistry", "JobSnapshot", "JobState", "jobs_segment_registration"]
