from __future__ import annotations

import asyncio
from dataclasses import replace
from time import monotonic

import pytest

from tinysoul.kernel.loop.inbox import WaitCondition, WaitReason, WakeReason, InboxCapacityError, InboxClosedError, InboxError, InboxKind, InboxLimits, InboxRecord, QuestionRequest, TurnInbox


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
    wait = asyncio.create_task(inbox.wait_for_cycle(WaitCondition(WaitReason.EVENT, 0, event_kind=InboxKind.EVENT)))
    await asyncio.sleep(0)
    await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "e"))
    assert await asyncio.wait_for(wait, 1)
    batch = await inbox.capture()
    assert batch.records
    assert not await inbox.close_if_empty()
    await inbox.ack(batch)
    wait = asyncio.create_task(inbox.wait_for_cycle(WaitCondition(WaitReason.EVENT, batch.next_sequence, event_kind=InboxKind.EVENT)))
    await asyncio.sleep(0)
    assert await inbox.close_if_empty()
    with pytest.raises(InboxClosedError):
        await asyncio.wait_for(wait, 1)
    with pytest.raises(InboxClosedError):
        await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "late"))


async def test_budget_decision_is_independent_of_full_progress_queue() -> None:
    inbox = TurnInbox(InboxLimits(capacity=1))
    await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "e"))
    request = await inbox.request_budget(3)
    waiter = asyncio.create_task(inbox.wait_for_cycle(budget=request))
    await asyncio.sleep(0)
    assert not waiter.done()
    assert await inbox.grant_cycles(request.request_id, 2)
    assert not await inbox.grant_cycles(request.request_id, 2)
    with pytest.raises(InboxError):
        await inbox.grant_cycles(request.request_id, 4)
    assert (await waiter).granted_cycles == 2
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
    assert (await inbox.wait_for_cycle(WaitCondition(WaitReason.INPUT, 0, question=question))).reason is WakeReason.REPLY
    batch = await inbox.capture()
    assert [record.kind for _, record in batch.records] == [InboxKind.EVENT, InboxKind.REPLY]
    await inbox.ack(batch)
    timed = QuestionRequest("timed", "choose", timeout_seconds=0.001)
    await inbox.open_question(timed)
    assert (await inbox.wait_for_cycle(WaitCondition(WaitReason.INPUT, batch.next_sequence,
        deadline=asyncio.get_running_loop().time() + 0.001, question=timed))).reason is WakeReason.TIMER
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


@pytest.mark.parametrize("grant_first", [False, True])
async def test_event_readiness_and_budget_must_both_arrive_without_consuming(grant_first: bool) -> None:
    inbox = TurnInbox()
    budget = await inbox.request_budget(3)
    condition = WaitCondition(WaitReason.EVENT, 0, event_kind=InboxKind.EVENT, event_id="matching")
    waiter = asyncio.create_task(inbox.wait_for_cycle(condition, budget=budget))
    await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "unrelated"))
    await asyncio.sleep(0)
    assert not waiter.done()
    if grant_first:
        await inbox.grant_cycles(budget.request_id, 2)
    else:
        await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "matching"))
    await asyncio.sleep(0)
    assert not waiter.done()
    if grant_first:
        await inbox.accept(InboxRecord(InboxKind.EVENT, {}, "matching"))
    else:
        await inbox.grant_cycles(budget.request_id, 2)
    readiness = await asyncio.wait_for(waiter, 1)
    assert readiness.reason is WakeReason.EVENT and readiness.granted_cycles == 2
    batch = await inbox.capture()
    assert [record.record_id for _, record in batch.records] == ["unrelated", "matching"]
    await inbox.ack(batch)
    next_wait = asyncio.create_task(inbox.wait_for_cycle(replace(condition, after_sequence=batch.next_sequence)))
    await asyncio.sleep(0)
    assert not next_wait.done()
    await inbox.close()
    with pytest.raises(InboxClosedError):
        await next_wait


@pytest.mark.parametrize("reason", [WaitReason.INPUT, WaitReason.EVENT, WaitReason.TIMER])
async def test_append_interrupts_wait_but_does_not_grant_budget(reason: WaitReason) -> None:
    inbox = TurnInbox()
    question = QuestionRequest("q", "choose") if reason is WaitReason.INPUT else None
    if question is not None:
        await inbox.open_question(question)
    condition = WaitCondition(
        reason, 0, question=question,
        deadline=monotonic() + 60 if reason is WaitReason.TIMER else None,
        event_kind=InboxKind.EVENT if reason is WaitReason.EVENT else None,
    )
    budget = await inbox.request_budget(1)
    waiter = asyncio.create_task(inbox.wait_for_cycle(condition, budget=budget))
    await inbox.accept(InboxRecord(InboxKind.INPUT, {"text": "new direction"}, "append"))
    await asyncio.sleep(0)
    assert not waiter.done()
    if question is not None:
        with pytest.raises(InboxClosedError):
            await inbox.reply(question.question_id, "late")
    await inbox.grant_cycles(budget.request_id, 1)
    assert (await asyncio.wait_for(waiter, 1)).reason is WakeReason.INPUT
    assert all(record.kind is not InboxKind.REPLY for _, record in (await inbox.capture()).records)


async def test_elapsed_timer_keeps_deadline_while_waiting_for_budget() -> None:
    inbox = TurnInbox()
    budget = await inbox.request_budget(1)
    waiter = asyncio.create_task(inbox.wait_for_cycle(
        WaitCondition(WaitReason.TIMER, 0, deadline=monotonic() - 1), budget=budget,
    ))
    await asyncio.sleep(0)
    assert not waiter.done()
    await inbox.grant_cycles(budget.request_id, 1)
    assert (await asyncio.wait_for(waiter, 1)).reason is WakeReason.TIMER
