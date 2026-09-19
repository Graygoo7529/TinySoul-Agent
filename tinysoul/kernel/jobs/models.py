"""Job facts and backend contract shared by supervisors and plugins."""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.infra.json import JsonObject
from .failures import JobError


class JobState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    STOPPING = "stopping"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    kind: str
    state: JobState
    summary: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.job_id, str)
            or not self.job_id
            or len(self.job_id) > 128
            or not isinstance(self.kind, str)
            or not self.kind
            or len(self.kind) > 64
            or not isinstance(self.state, JobState)
        ):
            raise JobError("Job snapshot requires typed state and identity")
        if not isinstance(self.summary, str) or len(self.summary) > 1000:
            raise JobError("Job summary must be bounded text")
        if not isinstance(self.reason, str) or len(self.reason) > 128:
            raise JobError("Job reason must be a bounded identifier")
        try:
            (self.job_id + self.kind + self.summary).encode("utf-8")
        except UnicodeError as exc:
            raise JobError("Job summaries must be valid UTF-8") from exc

    def to_json(self) -> JsonObject:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "state": self.state.value,
            "summary": self.summary,
            "reason": self.reason,
        }


class JobBackend(Protocol):
    """Local owner operations; polling must never wait for the external work."""

    def poll(self) -> JobSnapshot: ...

    def close_execution(self) -> tuple[CleanupDiagnostic, ...]: ...

    def cleanup(self) -> tuple[CleanupDiagnostic, ...]: ...

    def request_stop(self) -> None: ...

    def describe(self) -> JsonObject: ...
