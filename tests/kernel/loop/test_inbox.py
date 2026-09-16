from __future__ import annotations

import asyncio

import pytest

from tinysoul.kernel.loop.inbox import InboxCapacityError, InboxClosedError, InboxError, InboxKind, InboxLimits, InboxRecord, QuestionRequest, TurnInbox


async def test_fixed_batch_retries_exclude_new_arrivals_and_ack_preserves_identity() -> None:
    inbox = TurnInbox(InboxLimits(capacity=2))
    first = InboxRecord(InboxKind.INPUT, {"text": "one"}, "one")
    receipt = await inbox.accept(first)
    batch = await inbox.capture()
    await inbox.accept(InboxRecord(InboxKind.EVENT, {"value": 2}, "two"))
    assert await inbox.capture() is batch
    assert [item.record_id for _, item in batch.records] == ["one"]
    with pytest.raises(InboxCapacityError):
        await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "three"))
    await inbox.ack(batch)
    duplicate = await inbox.accept(first)
    assert duplicate.sequence == receipt.sequence and not duplicate.accepted
    with pytest.raises(InboxError):
        await inbox.accept(InboxRecord(InboxKind.INPUT, {"text": "different"}, "one"))
    assert [item.record_id for _, item in (await inbox.capture()).records] == ["two"]


async def test_wait_is_non_consuming_and_close_wakes_waiter() -> None:
    inbox = TurnInbox()
    wait = asyncio.create_task(inbox.wait())
    await asyncio.sleep(0)
    await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "e"))
    assert await asyncio.wait_for(wait, 1)
    batch = await inbox.capture()
    assert batch.records
    assert not await inbox.close_if_empty()
    await inbox.ack(batch)
    wait = asyncio.create_task(inbox.wait(after_sequence=batch.next_sequence))
    await asyncio.sleep(0)
    assert await inbox.close_if_empty()
    assert not await asyncio.wait_for(wait, 1)
    with pytest.raises(InboxClosedError):
        await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "late"))


async def test_budget_decision_is_independent_of_full_progress_queue() -> None:
    inbox = TurnInbox(InboxLimits(capacity=1))
    await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "e"))
    request = await inbox.request_budget(3)
    waiter = asyncio.create_task(inbox.wait_for_budget(request))
    await asyncio.sleep(0)
    assert not waiter.done()
    assert await inbox.grant_cycles(request.request_id, 2)
    assert not await inbox.grant_cycles(request.request_id, 2)
    with pytest.raises(InboxError):
        await inbox.grant_cycles(request.request_id, 4)
    assert await waiter == 2
    assert (await inbox.capture()).records


async def test_payload_snapshot_and_encoded_size_are_owned_by_inbox() -> None:
    inbox = TurnInbox(InboxLimits(max_record_bytes=90))
    record = InboxRecord(InboxKind.EVENT, {"text": "one"}, "e")
    await inbox.accept(record)
    record.payload["text"] = "changed"
    assert (await inbox.capture()).records[0][1].payload["text"] == "one"
    with pytest.raises(InboxCapacityError):
        await inbox.accept(InboxRecord(InboxKind.EVENT, {"text": "汉" * 30}, "large"))


async def test_reply_has_reserved_capacity_and_timeout_rejects_late_reply() -> None:
    inbox = TurnInbox(InboxLimits(capacity=1))
    await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "event"))
    question = QuestionRequest("q", "choose")
    await inbox.open_question(question)
    await inbox.reply("q", "yes")
    assert await inbox.wait_for_reply(question)
    batch = await inbox.capture()
    assert [record.kind for _, record in batch.records] == [InboxKind.EVENT, InboxKind.REPLY]
    await inbox.ack(batch)
    timed = QuestionRequest("timed", "choose", timeout_seconds=0.001)
    await inbox.open_question(timed)
    assert not await inbox.wait_for_reply(timed)
    with pytest.raises(InboxClosedError):
        await inbox.reply("timed", "late")


async def test_terminal_capacity_is_reserved_independently_from_progress() -> None:
    inbox = TurnInbox(InboxLimits(capacity=1, terminal_capacity=1))
    await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "progress"))
    await inbox.reserve_terminal("job")
    with pytest.raises(InboxCapacityError):
        await inbox.reserve_terminal("excess")
    await inbox.close()
    await inbox.deliver_terminal("job", {"state": "cancelled"})
    batch = await inbox.capture()
    assert [record.kind for _, record in batch.records] == [InboxKind.EVENT, InboxKind.JOB]
    await inbox.ack(batch)
