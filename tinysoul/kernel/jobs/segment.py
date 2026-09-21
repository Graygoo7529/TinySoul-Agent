"""Per-Turn Working projection of the Job owner's latest published snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from tinysoul.infra.json import JsonObject
from tinysoul.kernel.context.errors import ContextContractError
from tinysoul.kernel.context.segments import (
    SegmentDescriptor,
    SegmentRegistration,
    SegmentSlot,
    TurnInfo,
)
from tinysoul.llm.protocol.messages import Message, UserMessage
from tinysoul.runtime import Signal
from .models import JobSnapshot, JobState, JobInputRequest
from .failures import JobError


@dataclass(frozen=True)
class JobsUpdate:
    jobs: tuple[JobSnapshot, ...]

    def to_json(self) -> JsonObject:
        return {"jobs": [job.to_json() for job in self.jobs]}


class JobsSegment:
    def __init__(self) -> None:
        self._snapshot = JobsUpdate(())

    async def prepare(self, updates: tuple[JobsUpdate, ...]) -> JobsUpdate:
        return updates[-1] if updates else self._snapshot

    def install(self, prepared: JobsUpdate) -> None:
        self._snapshot = prepared

    def render(self) -> tuple[Message, ...]:
        return (
            (UserMessage.from_json(self._snapshot.to_json(), label="jobs"),)
            if self._snapshot.jobs
            else ()
        )

    def seal(self) -> JsonObject:
        return self._snapshot.to_json()

    async def close(self) -> None:
        self._snapshot = JobsUpdate(())


class JobsProvider:
    async def open(self, info: TurnInfo) -> JobsSegment:
        return JobsSegment()


def _decode(signal: Signal) -> JobsUpdate:
    jobs = signal.payload.get("jobs")
    if not isinstance(jobs, list):
        raise ContextContractError("Job snapshot requires a list")
    parsed: list[JobSnapshot] = []
    for job in jobs:
        if not isinstance(job, dict) or any(
            not isinstance(job.get(key), str)
            for key in ("job_id", "kind", "state", "summary")
        ):
            raise ContextContractError("Job snapshot contains invalid summary fields")
        job_id, kind, state, summary = (
            job["job_id"],
            job["kind"],
            job["state"],
            job["summary"],
        )
        assert (
            isinstance(job_id, str)
            and isinstance(kind, str)
            and isinstance(state, str)
            and isinstance(summary, str)
        )
        try:
            reason = job.get("reason", "")
            if not isinstance(reason, str):
                raise ContextContractError("Job reason must be text")
            pending = job.get("pending_inputs", [])
            if not isinstance(pending, list):
                raise ContextContractError("Job inputs must be a list")
            links = job.get("result_links", [])
            if not isinstance(links, list) or any(
                not isinstance(link, str) for link in links
            ):
                raise ContextContractError("Job result links must be a list of strings")
            parsed.append(
                JobSnapshot(
                    job_id,
                    kind,
                    JobState(state),
                    summary,
                    reason,
                    tuple(JobInputRequest.from_json(item) for item in pending),
                    tuple(link for link in links if isinstance(link, str)),
                )
            )
        except (ValueError, JobError) as exc:
            raise ContextContractError(
                "Job snapshot contains an invalid state"
            ) from exc
    return JobsUpdate(tuple(parsed))


def jobs_segment_registration() -> SegmentRegistration[JobsUpdate, JobsUpdate]:
    return SegmentRegistration(
        descriptor=SegmentDescriptor("jobs", "jobs", SegmentSlot.WORKING, 30),
        provider=JobsProvider(),
        signal_name="context.jobs",
        update_type=JobsUpdate,
        decode=_decode,
    )
