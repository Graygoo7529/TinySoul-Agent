from __future__ import annotations

import asyncio
import pytest

from tinysoul.runtime.generation import (
    RuntimeActivationState,
    RuntimeActivity,
    RuntimeGenerationError,
    RuntimeHandle,
)


async def test_runtime_handle_reads_and_replaces_generation() -> None:
    handle = RuntimeHandle("old", generation_id="generation_old")
    assert handle.snapshot().generation == "old"
    async with handle.read() as generation:
        assert generation == "old"

    handle.begin_activation()
    async with handle.write():
        generation_id = handle.activate("new", generation_id="generation_new")

    snapshot = handle.snapshot()
    assert generation_id == "generation_new"
    assert snapshot.generation == "new"
    assert snapshot.activation is RuntimeActivationState.ACTIVE


def test_runtime_handle_rejects_activation_while_active() -> None:
    handle = RuntimeHandle("old")
    handle.set_activity(RuntimeActivity.USER_TURN)
    with pytest.raises(RuntimeGenerationError, match="idle"):
        handle.begin_activation()


def test_runtime_handle_failed_activation_is_visible() -> None:
    handle = RuntimeHandle("old")
    handle.begin_activation()
    handle.fail_activation()
    assert handle.snapshot().activation is RuntimeActivationState.FAILED


async def test_runtime_activity_lease_reports_and_releases_activity() -> None:
    handle = RuntimeHandle("generation")

    async with handle.activity_lease(RuntimeActivity.REFLECTION_TURN):
        assert handle.activity is RuntimeActivity.REFLECTION_TURN
        with pytest.raises(RuntimeGenerationError, match="idle"):
            handle.begin_activation()

    assert handle.activity is RuntimeActivity.IDLE


async def test_new_work_does_not_block_failed_candidate_cleanup() -> None:
    handle = RuntimeHandle("original")
    handle.begin_activation()
    entered = asyncio.Event()

    async def work() -> None:
        async with handle.activity_lease(RuntimeActivity.USER_TURN):
            async with handle.read() as generation:
                assert generation == "original"
                entered.set()

    task = asyncio.create_task(work())
    try:
        await asyncio.sleep(0)
        assert not entered.is_set()
        # Candidate cleanup must be able to resume on this same event loop.
        handle.fail_activation()
        await asyncio.wait_for(task, 1)
        assert entered.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancelled_writer_releases_admission_and_close_rejects_new_use() -> None:
    handle = RuntimeHandle("active")

    async def write() -> None:
        async with handle.write():
            pytest.fail("Reader still owns its lease")

    async with handle.read():
        writer = asyncio.create_task(write())
        await asyncio.sleep(0)
        writer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await writer
        async with handle.read() as generation:
            assert generation == "active"
    await handle.close()
    with pytest.raises(RuntimeGenerationError, match="closed"):
        async with handle.read():
            pass
