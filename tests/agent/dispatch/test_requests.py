from __future__ import annotations
import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from tinysoul.agent import (
    AgentClosedError,
    AgentQueueFullError,
    AgentState,
    RequestFailure,
    TurnState,
    UserTurnRequest,
)
from tinysoul.infra.json import JsonObject
from tinysoul.infra.time import CalendarDay
from tinysoul.kernel.interaction import AnswerKind, QuestionAnswer
from tinysoul.kernel.loop.interaction.inbox import InboxClosedError, WaitReason
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.llm.protocol.responses import RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.runtime.events import EnvironmentEvent, EventKind
from tests.agent.support import (
    _Clock,
    _LLM,
    _create,
)

pytestmark = pytest.mark.integration


async def test_cancel_active_turn_keeps_dispatcher_and_queued_work_alive(
    tmp_path: Path,
) -> None:
    llm = _LLM()
    agent = await _create(tmp_path, llm)
    await agent.start()
    try:
        active = await agent.submit_turn(UserTurnRequest("one"))
        await asyncio.wait_for(llm.started.wait(), 3)
        queued = await agent.submit_turn(UserTurnRequest("two"))
        with pytest.raises(AgentQueueFullError):
            await agent.submit_turn(UserTurnRequest("three"))
        await agent.append_input(
            active.request_id, "accepted before cancellation", input_id="accepted"
        )
        assert await agent.cancel_request(active.request_id)
        cancelled = await asyncio.wait_for(active.wait(), 5)
        assert cancelled.status is TurnOutcomeStatus.CANCELLED
        assert isinstance(cancelled.outcome, TurnOutcome)
        facts = cancelled.outcome.context_completion
        assert facts is not None and facts.inputs[-1].input_id == "accepted"
        assert any(item.ref.endswith("#input/1") for item in facts.trace.timeline)
        assert active.state is TurnState.FINISHED
        assert agent.state is AgentState.RUNNING
        llm.release.set()
        result = await asyncio.wait_for(queued.wait(), 5)
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.answered
    finally:
        await agent.shutdown()


async def test_question_reply_resumes_same_turn_and_keeps_new_root_queued(
    tmp_path: Path,
) -> None:
    llm = _LLM()
    for call in reversed(
        (
            ToolCallRecord(
                "select_question",
                "select_action_domains",
                {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "ask",
                "core.ask",
                {
                    "question": "Choose a direction",
                    "options": [
                        {"id": "A", "label": "Direction A"},
                        {"id": "B", "label": "Direction B"},
                    ],
                },
                ToolKind.ACTION,
            ),
        )
    ):
        llm.results.appendleft(
            TaskResult.success(
                raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
                answer=None,
                tool_calls=(call,),
            )
        )
    llm.release.set()
    clock = _Clock()
    agent = await _create(tmp_path, llm, clock=clock)
    await agent.start()
    try:
        active = await agent.submit_turn(UserTurnRequest("plan"))
        async with asyncio.timeout(4):
            while active.wait_reason is not WaitReason.INPUT:
                await asyncio.sleep(0.01)
        question = active.question
        assert question is not None and not active.done
        clock.value = datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        queued = await agent.submit_turn(UserTurnRequest("later"))
        assert (
            await agent.publish(
                EnvironmentEvent(
                    EventKind.EVENT, {"changed": True}, "e", active.request_id
                )
            )
        ).delivered
        assert not (
            await agent.publish(
                EnvironmentEvent(EventKind.EVENT, {}, "stale", "previous_turn")
            )
        ).delivered
        with pytest.raises(InboxClosedError):
            await agent.reply(
                active.request_id,
                "old_question",
                QuestionAnswer(AnswerKind.TEXT, text="no"),
            )
        assert len(llm.calls) == 2 and queued.state is TurnState.QUEUED
        await agent.cancel_request(queued.request_id)
        receipt = await agent.reply(
            active.request_id,
            question.question_id,
            QuestionAnswer(AnswerKind.CHOICE, option_id="A"),
        )
        duplicate = await agent.reply(
            active.request_id,
            question.question_id,
            QuestionAnswer(AnswerKind.CHOICE, option_id="A"),
        )
        assert receipt.accepted and not duplicate.accepted
        result = await asyncio.wait_for(active.wait(), 5)
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.answered
        assert result.outcome.active_day == CalendarDay.parse("2026-09-15")
        completion = result.outcome.context_completion
        assert completion is not None
        reply = completion.inputs[-1]
        assert reply.text == "Direction A (A)" and reply.input_id == receipt.record_id
        assert reply.reply_to == question.question_id
        assert (await queued.wait()).status is RequestFailure.CANCELLED
        llm.results.extend(_LLM().results)
        following = await agent.submit_turn(UserTurnRequest("new day"))
        new_result = await asyncio.wait_for(following.wait(), 5)
        assert isinstance(new_result.outcome, TurnOutcome)
        assert new_result.outcome.active_day == CalendarDay.parse("2026-09-16")
        assert tuple((tmp_path / "project" / "archive").glob("*/session/turns/*.json"))
    finally:
        await agent.shutdown()


@pytest.mark.parametrize("wait_kind", ["event", "timer", "question"])
async def test_append_resumes_unified_wait_on_same_turn(
    tmp_path: Path, wait_kind: str
) -> None:
    llm = _LLM()
    action = "core.ask" if wait_kind == "question" else "core.wait"
    params: JsonObject = (
        {"question": "Choose"}
        if wait_kind == "question"
        else (
            {"event_kind": "event", "event_id": "matching"}
            if wait_kind == "event"
            else {"timeout_seconds": 60}
        )
    )
    for call in reversed(
        (
            ToolCallRecord(
                "select_wait",
                "select_action_domains",
                {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord("wait", action, params, ToolKind.ACTION),
        )
    ):
        llm.results.appendleft(
            TaskResult.success(
                raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
                answer=None,
                tool_calls=(call,),
            )
        )
    llm.release.set()
    agent = await _create(tmp_path, llm)
    await agent.start()
    try:
        handle = await agent.submit_turn(UserTurnRequest("wait"))
        async with asyncio.timeout(5):
            while handle.wait_reason is None:
                assert not handle.done
                await asyncio.sleep(0.01)
        question = handle.question
        queued = await agent.submit_turn(UserTurnRequest("next root"))
        await agent.publish(EnvironmentEvent(EventKind.EVENT, {}, "unrelated"))
        await asyncio.sleep(0)
        assert len(llm.calls) == 2 and queued.state is TurnState.QUEUED
        await agent.cancel_request(queued.request_id)
        receipt = await agent.append_input(
            handle.request_id, "Change direction", input_id="new"
        )
        result = await asyncio.wait_for(handle.wait(), 5)
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.answered
        completion = result.outcome.context_completion
        assert completion is not None and completion.turn_id == handle.turn_id
        assert completion.inputs[-1].input_id == receipt.record_id
        assert completion.inputs[-1].reply_to == ""
        if question is not None:
            with pytest.raises(AgentClosedError):
                await agent.reply(
                    handle.request_id,
                    question.question_id,
                    QuestionAnswer(AnswerKind.TEXT, text="late"),
                )
    finally:
        await agent.shutdown()


async def test_sdk_finalizing_rejects_late_cancel_and_preserves_session_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event

    from tinysoul.plugins.session import SessionEngine

    llm = _LLM()
    llm.release.set()
    entered, release = asyncio.Event(), Event()
    loop = asyncio.get_running_loop()
    original = SessionEngine.record_turn

    def record(owner, *args, **kwargs):
        original(owner, *args, **kwargs)
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)

    monkeypatch.setattr(SessionEngine, "record_turn", record)
    agent = await _create(tmp_path, llm)
    await agent.start()
    try:
        handle = await agent.submit_turn(UserTurnRequest("answer"))
        await asyncio.wait_for(entered.wait(), 4)
        assert handle.state is TurnState.FINALIZING
        assert not await agent.cancel_request(handle.request_id)
        stopping = asyncio.create_task(agent.shutdown())
        await asyncio.sleep(0)
        assert not stopping.done()
        release.set()
        await asyncio.wait_for(stopping, 5)
        result = await handle.wait()
        assert result.status is TurnOutcomeStatus.ANSWERED
        assert (
            len(
                tuple(
                    (tmp_path / "project" / "runtime" / "session").rglob("turns/*.json")
                )
            )
            == 1
        )
    finally:
        release.set()
        await agent.shutdown()
