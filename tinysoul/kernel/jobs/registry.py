"""Supervise backend lifetimes and retain bounded, authoritative Job summaries."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import uuid4

from tinysoul.infra.concurrency import CleanupDiagnostic, JoinedOperations
from tinysoul.infra.json import JsonObject, to_json_object
from tinysoul.kernel.loop.interaction.inbox import InboxError, TurnInbox
from tinysoul.runtime import RunScope, Signal, SignalBus
from tinysoul.runtime.control.exception import RUNTIME_AGENT_END
from .failures import JobError, JobRequestError, JobFailureKind
from .runtime_bridge import RuntimeJobsBridge
from .models import JobState, JobSnapshot, JobBackend


@dataclass
class _Job[B: JobBackend]:
    turn_id: str
    snapshot: JobSnapshot
    backend: B | None = None
    monitor: asyncio.Task[None] | None = None
    terminal_delivered: bool = False
    execution_closed: bool = False
    failure: JobError | None = None
    control_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class JobRegistry[B: JobBackend]:
    """Supervise execution once; retain a bounded set of terminal results."""

    def __init__(self, *, capacity: int = 16, per_turn_capacity: int = 1) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (capacity, per_turn_capacity)
        ):
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
        if not isinstance(turn_id, str) or not turn_id:
            raise JobRequestError("Job requires an owner Turn")
        active = tuple(job for job in self._jobs.values() if not job.execution_closed)
        if sum(job.turn_id == turn_id for job in active) >= self._per_turn_capacity:
            raise JobRequestError("Turn already owns its maximum live Jobs")
        if len(self._jobs) >= self._capacity:
            raise JobRequestError(
                "Retained Job result capacity is full; finish this Turn before starting more work"
            )
        job_id = f"job_{uuid4().hex}"
        job = _Job[B](turn_id, JobSnapshot(job_id, kind, JobState.STARTING))
        self._jobs[job_id] = job
        inbox = self._inboxes.get(turn_id)
        try:
            if inbox is not None:
                try:
                    await inbox.reserve_terminal(job_id, required_bytes=8192)
                except InboxError as exc:
                    raise JobRequestError(
                        "Job terminal capacity is unavailable"
                    ) from exc
            operations = JoinedOperations()
            job.backend = await operations.run(lambda: factory(job_id))
            operations.check_cancelled()
            job.monitor = asyncio.create_task(
                self._monitor(job), name=f"tinysoul-job:{job_id}"
            )
            return job.backend
        except BaseException:
            await self.release(turn_id, job_id)
            raise

    def _owned(self, turn_id: str, job_id: str) -> _Job[B]:
        job = self._jobs.get(job_id)
        if job is None or job.turn_id != turn_id or job.backend is None:
            raise JobRequestError("Job is not available in this Turn")
        return job

    def get(self, turn_id: str, job_id: str) -> B:
        job = self._owned(turn_id, job_id)
        if job.failure is not None:
            raise job.failure
        assert job.backend is not None
        return job.backend

    def ids(self, turn_id: str) -> tuple[str, ...]:
        return tuple(key for key, job in self._jobs.items() if job.turn_id == turn_id)

    def has_unresolved(self, turn_id: str) -> bool:
        return any(
            not job.execution_closed
            for job in self._jobs.values()
            if job.turn_id == turn_id
        )

    def snapshots(self, turn_id: str) -> tuple[JobSnapshot, ...]:
        return tuple(
            job.snapshot for job in self._jobs.values() if job.turn_id == turn_id
        )

    def snapshot(self, turn_id: str, job_id: str) -> JobSnapshot:
        self.get(turn_id, job_id)
        return self._jobs[job_id].snapshot

    async def describe(
        self, turn_id: str, job_id: str, *, operations: JoinedOperations
    ) -> JsonObject:
        backend = self.get(turn_id, job_id)
        details = await self._call(backend.describe, operations=operations)
        return {
            **self.snapshot(turn_id, job_id).to_json(),
            "details": to_json_object(details),
        }

    async def stop(
        self, turn_id: str, job_id: str, *, operations: JoinedOperations
    ) -> JobSnapshot:
        job = self._owned(turn_id, job_id)
        async with job.control_lock:
            self._owned(turn_id, job_id)
            try:
                await self._join_monitor(job)
                if not job.execution_closed:
                    assert job.backend is not None
                    job.snapshot = JobSnapshot(job_id, job.snapshot.kind, JobState.STOPPING)
                    await self._call(
                        job.backend.request_stop,
                        operations=operations,
                        kind=JobFailureKind.EXECUTION_CLOSE_FAILED,
                    )
                    await self._close_execution(job)
                    snapshot = await self._poll(job)
                    if not snapshot.state.terminal:
                        raise JobError(
                            "Backend reported a live Job after closing execution",
                            kind=JobFailureKind.EXECUTION_CLOSE_FAILED,
                        )
                    job.snapshot = snapshot
                    await self._terminal(job)
                if job.failure is not None:
                    raise job.failure
                return job.snapshot
            except JobError as exc:
                # External controls must leave a failure fact for the Turn's
                # existing sync/Trap path after retiring the monitor.
                job.failure = exc
                await self._terminal(job)
                raise

    async def _call[T](
        self,
        operation: Callable[[], T],
        *,
        operations: JoinedOperations | None = None,
        kind: JobFailureKind = JobFailureKind.SUPERVISION_FAILED,
    ) -> T:
        try:
            joined = operations or JoinedOperations()
            value = await joined.run(operation)
            if operations is None:
                joined.check_cancelled()
            return value
        except JobError:
            raise
        except Exception as exc:
            raise JobError(
                "Job backend could not complete its operation", kind=kind
            ) from exc

    async def _poll(self, job: _Job[B]) -> JobSnapshot:
        assert job.backend is not None
        snapshot = await self._call(job.backend.poll)
        if (
            not isinstance(snapshot, JobSnapshot)
            or snapshot.job_id != job.snapshot.job_id
            or snapshot.kind != job.snapshot.kind
        ):
            raise JobError("Backend changed Job identity")
        return snapshot

    async def _close_execution(self, job: _Job[B]) -> None:
        if job.execution_closed or job.backend is None:
            return
        diagnostics = await self._call(
            job.backend.close_execution, kind=JobFailureKind.EXECUTION_CLOSE_FAILED
        )
        self._record_diagnostics(job.turn_id, diagnostics)
        job.execution_closed = True

    def _record_diagnostics(
        self, turn_id: str, diagnostics: tuple[CleanupDiagnostic, ...]
    ) -> None:
        if not isinstance(diagnostics, tuple) or any(
            not isinstance(item, CleanupDiagnostic) for item in diagnostics
        ):
            raise JobError("Backend cleanup must return typed diagnostics")
        self._diagnostics.setdefault(turn_id, []).extend(diagnostics)

    async def _monitor(self, job: _Job[B]) -> None:
        try:
            while True:
                snapshot = await self._poll(job)
                if snapshot.state.terminal:
                    await self._close_execution(job)
                    job.snapshot = snapshot
                    await self._terminal(job)
                    return
                job.snapshot = snapshot
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except JobError as exc:
            job.failure = exc
            try:
                if exc.kind is not JobFailureKind.EXECUTION_CLOSE_FAILED:
                    await self._close_execution(job)
            except JobError as close_error:
                job.failure = close_error
            if job.execution_closed and not job.snapshot.state.terminal:
                job.snapshot = JobSnapshot(
                    job.snapshot.job_id,
                    job.snapshot.kind,
                    JobState.FAILED,
                    "Execution closed after a supervision failure.",
                )
            # Wake the waiting Turn even on a necessary failure. RUNNING is kept
            # when execution could not close; no invented STOPPED terminal.
            await self._terminal(job)

    async def _terminal(self, job: _Job[B]) -> None:
        if job.terminal_delivered:
            return
        inbox = self._inboxes.get(job.turn_id)
        if inbox is not None:
            try:
                await inbox.deliver_terminal(
                    job.snapshot.job_id, job.snapshot.to_json()
                )
            except InboxError as exc:
                raise JobError("Reserved Job delivery failed") from exc
        job.terminal_delivered = True

    async def _join_monitor(self, job: _Job[B]) -> None:
        if job.monitor is not None:
            job.monitor.cancel()
            try:
                await job.monitor
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                raise JobError(
                    "Job monitor failed", kind=JobFailureKind.SUPERVISION_FAILED
                ) from exc
            job.monitor = None

    async def release(self, turn_id: str, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        if job.turn_id != turn_id:
            raise JobRequestError("Cannot release another Turn's Job")

        async def close() -> None:
            async with job.control_lock:
                if job_id not in self._jobs:
                    return
                await self._join_monitor(job)
                if job.backend is not None:
                    if not job.execution_closed:
                        await self._close_execution(job)
                        try:
                            job.snapshot = await self._poll(job)
                        except JobError as exc:
                            job.failure = job.failure or exc
                            job.snapshot = JobSnapshot(
                                job_id,
                                job.snapshot.kind,
                                JobState.FAILED,
                                "Execution closed; final result is unavailable.",
                            )
                        if not job.snapshot.state.terminal:
                            job.execution_closed = False
                            raise JobError(
                                "Backend reported a live Job after closing execution",
                                kind=JobFailureKind.EXECUTION_CLOSE_FAILED,
                            )
                    self._record_diagnostics(turn_id, await self._call(job.backend.cleanup))
                    await self._terminal(job)
                inbox = self._inboxes.get(turn_id)
                if inbox is not None:
                    await inbox.release_terminal(job_id)
                self._jobs.pop(job_id, None)
                if job.failure is not None:
                    raise job.failure

        operation = JoinedOperations()
        try:
            await operation.run_async(close)
        except JobError as exc:
            raise RuntimeJobsBridge().from_error(exc) from exc
        operation.check_cancelled()

    async def cleanup_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
        from tinysoul.runtime import RuntimeException

        failure: RuntimeException | None = None
        for job_id in self.ids(turn_id):
            try:
                await self.release(turn_id, job_id)
            except RuntimeException as exc:
                if failure is None or exc.reason == RUNTIME_AGENT_END:
                    failure = exc
        if not self.ids(turn_id):
            self._inboxes.pop(turn_id, None)
        if failure is not None:
            raise failure
        return tuple(self._diagnostics.pop(turn_id, ()))

    def sync(self, turn_id: str, *, bus: SignalBus, scope: RunScope) -> None:
        bus.emit(
            Signal(
                name="context.jobs",
                source="kernel.jobs",
                scope=scope,
                payload={"jobs": [item.to_json() for item in self.snapshots(turn_id)]},
            )
        )
        for job in self._jobs.values():
            if job.turn_id == turn_id and job.failure is not None:
                raise RuntimeJobsBridge().from_error(job.failure)
