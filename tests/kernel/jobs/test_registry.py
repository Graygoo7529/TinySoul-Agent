from __future__ import annotations

import asyncio
from threading import Event

import pytest

from tinysoul.kernel.jobs import JobError, JobRegistry, JobSnapshot, JobState
from tinysoul.kernel.loop.inbox import InboxCapacityError, InboxKind, InboxLimits, InboxRecord, TurnInbox


class _Backend:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.finished = Event()
        self.closed = Event()
        self.cleaned = Event()

    def poll(self) -> JobSnapshot:
        return JobSnapshot(self.job_id, "test", JobState.SUCCEEDED if self.finished.is_set() else JobState.RUNNING)

    def close_execution(self) -> None:
        self.closed.set()

    def cleanup(self) -> None:
        self.close_execution()
        self.cleaned.set()


async def test_terminal_reservation_survives_full_and_closed_ordinary_ingress() -> None:
    inbox = TurnInbox(InboxLimits(capacity=1, max_bytes=500, max_record_bytes=400))
    registry = JobRegistry[_Backend]()
    registry.bind_inbox("turn", inbox)
    backend = await registry.start("turn", "test", _Backend)
    await inbox.accept(InboxRecord(InboxKind.EVENT, {"progress": 1}))
    await inbox.close()
    backend.finished.set()
    async with asyncio.timeout(2):
        while not backend.closed.is_set():
            await asyncio.sleep(0.01)
    # Closing the execution handle does not delete owner output or candidates.
    assert not backend.cleaned.is_set()
    await registry.cleanup_turn("turn")
    batch = await inbox.capture()
    assert [record.kind for _, record in batch.records] == [InboxKind.EVENT, InboxKind.JOB]
    assert batch.records[-1][1].payload["state"] == "succeeded"
    await inbox.ack(batch)
    assert await inbox.close_if_empty()
    assert backend.cleaned.is_set() and not registry.has_unresolved("turn")


async def test_terminal_bytes_are_reserved_before_backend_launch() -> None:
    registry = JobRegistry[_Backend]()
    registry.bind_inbox("turn", TurnInbox(InboxLimits(max_terminal_bytes=100)))
    launched: list[str] = []

    def launch(job_id: str) -> _Backend:
        launched.append(job_id)
        return _Backend(job_id)

    with pytest.raises(JobError):
        await registry.start("turn", "test", launch)
    assert not launched and not registry.has_unresolved("turn")


async def test_launch_cancellation_joins_owner_then_cleans_created_backend() -> None:
    entered = Event()
    release = Event()
    backends: list[_Backend] = []

    def factory(job_id: str) -> _Backend:
        entered.set()
        release.wait(2)
        backend = _Backend(job_id)
        backends.append(backend)
        return backend

    registry = JobRegistry[_Backend]()
    launch = asyncio.create_task(registry.start("turn", "test", factory))
    async with asyncio.timeout(2):
        while not entered.is_set():
            await asyncio.sleep(0.01)
    launch.cancel()
    await asyncio.sleep(0)
    assert not launch.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await launch
    assert backends[0].cleaned.is_set() and not registry.has_unresolved("turn")


async def test_failed_poll_still_reclaims_backend_and_keeps_bounded_diagnostics() -> None:
    class FailingBackend(_Backend):
        def poll(self) -> JobSnapshot:
            raise OSError("private owner path")

    registry = JobRegistry[FailingBackend]()
    backend = await registry.start("turn", "test", FailingBackend)
    diagnostics = await registry.cleanup_turn("turn")
    assert backend.cleaned.is_set()
    assert diagnostics and all("private" not in repr(item) for item in diagnostics)
