from __future__ import annotations

import asyncio
from threading import Thread

import pytest

from tinysoul.infra.concurrency import AsyncMailbox, AsyncResourceScope, ConcurrencyContractError


async def test_resource_scope_retains_failures_and_closes_once_in_reverse_order() -> None:
    scope = AsyncResourceScope()
    calls: list[str] = []

    async def first() -> None:
        calls.append("first")

    async def second() -> None:
        calls.append("second")
        raise RuntimeError("private client credentials")

    scope.register("first", first)
    scope.register("second", second)
    left, right = await asyncio.gather(scope.close(), scope.close())
    assert calls == ["second", "first"]
    assert left == right == await scope.close()
    assert [(item.resource, item.error_type) for item in left] == [("second", "RuntimeError")]
    with pytest.raises(ConcurrencyContractError):
        scope.register("late", first)


async def test_repeated_close_cancellation_waits_for_all_owned_resources() -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    scope = AsyncResourceScope()
    closed: list[str] = []

    async def close() -> None:
        entered.set()
        await release.wait()
        closed.append("resource")

    scope.register("resource", close)
    task = asyncio.create_task(scope.close())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == ["resource"]
    assert await scope.close() == ()


async def test_mailbox_idle_cancel_keeps_later_input_and_wakes_from_thread() -> None:
    mailbox = AsyncMailbox[str]()
    waiter = asyncio.create_task(mailbox.get())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    worker = Thread(target=mailbox.put, args=("accepted",))
    worker.start()
    assert await asyncio.wait_for(mailbox.get(), 1) == "accepted"
    worker.join()
    waiter = asyncio.create_task(mailbox.get())
    await asyncio.sleep(0)
    mailbox.put("next")
    assert await asyncio.wait_for(waiter, 1) == "next"
