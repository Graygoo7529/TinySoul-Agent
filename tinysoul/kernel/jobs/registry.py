"""Supervise backend lifetimes and retain bounded, authoritative Job summaries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.kernel.loop.inbox import InboxError, TurnInbox
from tinysoul.runtime import RunScope, Signal, SignalBus


class JobError(Exception):
    """Job admission, identity or execution resource contract failed."""


class JobState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    kind: str
    state: JobState
    summary: str = ""

    def __post_init__(self) -> None:
        if (not isinstance(self.job_id, str) or not self.job_id or len(self.job_id) > 128
                or not isinstance(self.kind, str) or not self.kind or len(self.kind) > 64
                or not isinstance(self.state, JobState)):
            raise JobError("Job snapshot requires typed state and identity")
        if not isinstance(self.summary, str) or len(self.summary) > 1000:
            raise JobError("Job summary must be bounded text")
        try:
            (self.job_id + self.kind + self.summary).encode("utf-8")
        except UnicodeError as exc:
            raise JobError("Job summaries must be valid UTF-8") from exc

    def to_json(self) -> JsonObject:
        return {"job_id": self.job_id, "kind": self.kind,
                "state": self.state.value, "summary": self.summary}


class JobBackend(Protocol):
    """Local owner operations; polling must never wait for the external work."""

    def poll(self) -> JobSnapshot: ...

    def close_execution(self) -> None: ...

    def cleanup(self) -> None: ...

    def request_stop(self) -> None: ...

    def describe(self) -> JsonObject: ...


@dataclass
class _Job[B: JobBackend]:
    turn_id: str
    snapshot: JobSnapshot
    backend: B | None = None
    monitor: asyncio.Task[None] | None = None
    terminal_delivered: bool = False


class JobRegistry[B: JobBackend]:
    """One supervisor and one reserved terminal record for each accepted Job."""

    def __init__(self, *, capacity: int = 16, per_turn_capacity: int = 1) -> None:
        if any(type(value) is not int or value <= 0 for value in (capacity, per_turn_capacity)):
            raise JobError("Job limits must be positive integers")
        self._capacity = capacity
        self._per_turn_capacity = per_turn_capacity
        self._jobs: dict[str, _Job[B]] = {}
        self._inboxes: dict[str, TurnInbox] = {}
        self._diagnostics: dict[str, list[CleanupDiagnostic]] = {}

    def bind_inbox(self, turn_id: str, inbox: TurnInbox | None) -> None:
        if not isinstance(turn_id, str) or not turn_id:
            raise JobError("Job owner Turn identity is required")
        if turn_id in self._inboxes and self._inboxes[turn_id] is not inbox:
            raise JobError("Job owner Inbox cannot change during a Turn")
        if inbox is not None:
            self._inboxes[turn_id] = inbox

    async def start(self, turn_id: str, kind: str, factory: Callable[[str], B]) -> B:
        if (len(self._jobs) >= self._capacity
                or sum(job.turn_id == turn_id for job in self._jobs.values()) >= self._per_turn_capacity):
            raise JobError("Turn already owns its maximum unresolved Jobs")
        job_id = f"job_{uuid4().hex}"
        job = _Job[B](turn_id, JobSnapshot(job_id, kind, JobState.RUNNING))
        self._jobs[job_id] = job
        inbox = self._inboxes.get(turn_id)
        try:
            if inbox is not None:
                # Includes JSON escaping of every bounded summary character;
                # reject before launch if the Inbox cannot retain a terminal.
                try:
                    await inbox.reserve_terminal(job_id, required_bytes=8192)
                except InboxError as exc:
                    raise JobError("Job terminal capacity is unavailable") from exc
            operations = JoinedOperations()
            job.backend = await operations.run(lambda: factory(job_id))
            operations.check_cancelled()
            job.monitor = asyncio.create_task(self._monitor(job), name=f"tinysoul-job:{job_id}")
            return job.backend
        except BaseException:
            await self.release(turn_id, job_id)
            raise

    def get(self, turn_id: str, job_id: str) -> B:
        job = self._jobs.get(job_id)
        if job is None or job.turn_id != turn_id or job.backend is None:
            raise JobError("Job is not active in this Turn")
        return job.backend

    def ids(self, turn_id: str) -> tuple[str, ...]:
        return tuple(key for key, job in self._jobs.items() if job.turn_id == turn_id)

    def has_unresolved(self, turn_id: str) -> bool:
        return bool(self.ids(turn_id))

    def snapshots(self, turn_id: str) -> tuple[JobSnapshot, ...]:
        return tuple(job.snapshot for job in self._jobs.values() if job.turn_id == turn_id)

    def snapshot(self, turn_id: str, job_id: str) -> JobSnapshot:
        self.get(turn_id, job_id)
        return self._jobs[job_id].snapshot

    async def describe(self, turn_id: str, job_id: str, *, operations: JoinedOperations) -> JsonObject:
        backend = self.get(turn_id, job_id)
        details = await operations.run(backend.describe)
        return {**self.snapshot(turn_id, job_id).to_json(), "details": to_json_object(details)}

    async def stop(self, turn_id: str, job_id: str, *, operations: JoinedOperations) -> JobSnapshot:
        backend = self.get(turn_id, job_id)
        job = self._jobs[job_id]
        if job.snapshot.state is JobState.RUNNING:
            await operations.run(backend.request_stop)
            # The monitor alone publishes the terminal snapshot and fact.
            monitor = job.monitor
            if monitor is not None:
                await operations.finish(lambda: monitor)
        return job.snapshot

    async def _monitor(self, job: _Job[B]) -> None:
        backend = job.backend
        if backend is None:
            raise JobError("Cannot supervise an unstarted Job")
        operations = JoinedOperations()
        try:
            while True:
                snapshot = await operations.run(backend.poll)
                if snapshot.job_id != job.snapshot.job_id or snapshot.kind != job.snapshot.kind:
                    raise JobError("Backend changed Job identity")
                job.snapshot = snapshot
                operations.check_cancelled()
                if snapshot.state is not JobState.RUNNING:
                    await operations.run(backend.close_execution)
                    await self._terminal(job)
                    return
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._diagnostics.setdefault(job.turn_id, []).append(
                CleanupDiagnostic("job.monitor", type(exc).__name__),
            )
            if job.snapshot.state is JobState.RUNNING:
                job.snapshot = JobSnapshot(job.snapshot.job_id, job.snapshot.kind,
                                           JobState.FAILED, "Job supervision failed.")
            try:
                await JoinedOperations().run(backend.close_execution)
            except Exception as close_error:
                self._diagnostics[job.turn_id].append(
                    CleanupDiagnostic("job.execution", type(close_error).__name__),
                )
            await self._terminal(job)

    async def _terminal(self, job: _Job[B]) -> None:
        if job.terminal_delivered:
            return
        inbox = self._inboxes.get(job.turn_id)
        if inbox is not None:
            await inbox.deliver_terminal(job.snapshot.job_id, job.snapshot.to_json())
        job.terminal_delivered = True

    async def release(self, turn_id: str, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        if job.turn_id != turn_id:
            raise JobError("Cannot release another Turn's Job")
        # Always join the monitor before touching its owner resources.
        async def close() -> None:
            if job.monitor is not None:
                job.monitor.cancel()
                try:
                    await job.monitor
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    self._diagnostics.setdefault(turn_id, []).append(
                        CleanupDiagnostic("job.monitor", type(exc).__name__),
                    )
            if job.backend is not None:
                try:
                    if job.snapshot.state is JobState.RUNNING:
                        job.snapshot = await JoinedOperations().run(job.backend.poll)
                    if job.snapshot.state is JobState.RUNNING:
                        job.snapshot = JobSnapshot(job_id, job.snapshot.kind, JobState.STOPPED)
                except Exception as exc:
                    self._diagnostics.setdefault(turn_id, []).append(
                        CleanupDiagnostic("job.final_state", type(exc).__name__),
                    )
                    if job.snapshot.state is JobState.RUNNING:
                        job.snapshot = JobSnapshot(job_id, job.snapshot.kind, JobState.FAILED,
                                                   "Job final state could not be read.")
                try:
                    await JoinedOperations().run(job.backend.cleanup)
                except Exception as exc:
                    self._diagnostics.setdefault(turn_id, []).append(
                        CleanupDiagnostic("job.cleanup", type(exc).__name__),
                    )
                try:
                    await self._terminal(job)
                except Exception as exc:
                    self._diagnostics.setdefault(turn_id, []).append(
                        CleanupDiagnostic("job.terminal", type(exc).__name__),
                    )
            try:
                inbox = self._inboxes.get(turn_id)
                if inbox is not None:
                    await inbox.release_terminal(job_id)
            finally:
                self._jobs.pop(job_id, None)

        closer = asyncio.create_task(close())
        cancelled = False
        while not closer.done():
            try:
                await asyncio.shield(closer)
            except asyncio.CancelledError:
                cancelled = True
        closer.result()
        if cancelled:
            raise asyncio.CancelledError

    async def cleanup_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        for job_id in self.ids(turn_id):
            await self.release(turn_id, job_id)
        self._inboxes.pop(turn_id, None)
        return tuple(self._diagnostics.pop(turn_id, ()))

    def sync(self, turn_id: str, *, bus: SignalBus, scope: RunScope) -> None:
        bus.emit(Signal(
            name="context.jobs", source="kernel.jobs", scope=scope,
            payload={"jobs": [item.to_json() for item in self.snapshots(turn_id)]},
        ))
