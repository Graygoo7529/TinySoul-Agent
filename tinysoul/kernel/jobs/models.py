"""Job facts and backend contract shared by supervisors and plugins."""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.json import JsonObject, dumps_json
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
class JobInputOption:
    option_id: str
    label: str

    def __post_init__(self) -> None:
        if (
            not self.option_id
            or len(self.option_id) > 128
            or not self.label
            or len(self.label) > 256
        ):
            raise JobError("Job input option requires bounded identity and label")


class JobInputKind(StrEnum):
    PERMISSION = "permission"


@dataclass(frozen=True)
class JobInputRequest:
    request_id: str
    question: str
    options: tuple[JobInputOption, ...]
    kind: JobInputKind = JobInputKind.PERMISSION

    def __post_init__(self) -> None:
        if not isinstance(self.kind, JobInputKind):
            raise JobError("Job input requires a typed request kind")
        if (
            not self.request_id
            or len(self.request_id) > 128
            or not self.question
            or len(self.question) > 1000
        ):
            raise JobError("Job input requires bounded identity and question")
        if not 1 <= len(self.options) <= 8 or len(
            {item.option_id for item in self.options}
        ) != len(self.options):
            raise JobError("Job input requires distinct bounded options")
        if len(dumps_json(self.to_json()).encode("utf-8")) > 7000:
            raise JobError("Job input exceeds its delivery bound")

    def to_json(self) -> JsonObject:
        return {
            "request_id": self.request_id,
            "kind": self.kind.value,
            "question": self.question,
            "options": [
                {"option_id": item.option_id, "label": item.label}
                for item in self.options
            ],
        }

    @classmethod
    def from_json(cls, value: object) -> JobInputRequest:
        if not isinstance(value, dict):
            raise JobError("Job input requires an object")
        request_id, question, raw_options = (
            value.get("request_id"),
            value.get("question"),
            value.get("options"),
        )
        if (
            not isinstance(request_id, str)
            or not isinstance(question, str)
            or not isinstance(raw_options, list)
        ):
            raise JobError("Job input fields are invalid")
        options: list[JobInputOption] = []
        for item in raw_options:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("option_id"), str)
                or not isinstance(item.get("label"), str)
            ):
                raise JobError("Job input option is invalid")
            option_id, label = item.get("option_id"), item.get("label")
            assert isinstance(option_id, str) and isinstance(label, str)
            options.append(JobInputOption(option_id, label))
        try:
            kind = JobInputKind(value.get("kind"))
        except ValueError as exc:
            raise JobError("Job input kind is invalid") from exc
        return cls(request_id, question, tuple(options), kind)


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    kind: str
    state: JobState
    summary: str = ""
    reason: str = ""
    pending_inputs: tuple[JobInputRequest, ...] = ()
    result_links: tuple[str, ...] = ()

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
        if len(self.pending_inputs) > 4 or any(
            not isinstance(item, JobInputRequest) for item in self.pending_inputs
        ):
            raise JobError("Job pending inputs must be typed and bounded")
        if bool(self.pending_inputs) != (self.state is JobState.WAITING_INPUT):
            raise JobError("Waiting Job state must describe its pending inputs")
        if len(self.result_links) > 8 or any(
            not isinstance(link, str)
            or not link.startswith("workspace:")
            or len(link) > 512
            for link in self.result_links
        ):
            raise JobError("Job results require bounded Workspace links")
        try:
            (self.job_id + self.kind + self.summary).encode("utf-8")
        except UnicodeError as exc:
            raise JobError("Job summaries must be valid UTF-8") from exc

    @property
    def ready(self) -> bool:
        return self.state.terminal or bool(self.pending_inputs)

    def to_json(self) -> JsonObject:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "state": self.state.value,
            "summary": self.summary,
            "reason": self.reason,
            "pending_inputs": [item.to_json() for item in self.pending_inputs],
            "result_links": list(self.result_links),
        }


class JobBackend(Protocol):
    """Local owner operations; polling must never wait for the external work."""

    async def poll(self) -> JobSnapshot: ...

    async def close_execution(self) -> tuple[CleanupDiagnostic, ...]: ...

    async def cleanup(self) -> tuple[CleanupDiagnostic, ...]: ...

    async def request_stop(self) -> None: ...

    async def describe(self) -> JsonObject: ...


class JobControl(Protocol):
    """Owner supervision surface for hosts; no execution backend access."""

    def snapshots(self, turn_id: str) -> tuple[JobSnapshot, ...]: ...

    async def stop(
        self, turn_id: str, job_id: str, *, operations: JoinedOperations
    ) -> JobSnapshot: ...
