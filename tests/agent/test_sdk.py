from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import deque
from pathlib import Path

import pytest

from tinysoul.agent import Agent, AgentClosedError, AgentQueueFullError, AgentState, TurnState, UserTurnRequest
from tinysoul.agent import InboxLimits, InboxCapacityError, ObservationFilter, ObservationRecord
from tinysoul.agent.config import AgentSettings
from tinysoul.agent.assembly import AgentAssembly
from tinysoul.agent.builder import AgentBuilder
from tinysoul.infra.config import ConfigEnvironment, ConfigMutation, ConfigError
from tinysoul.plugins.workspace import WorkspaceEngine
from tinysoul.plugins.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.plugins.reflection import (ReflectionRequest, ReflectionScope, ReflectionTrigger, ReflectionOutcome, ReflectionStatus)
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.llm.tools import ToolCallRecord, ToolKind
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.kernel.loop.inbox import InboxClosedError, WaitReason
from tinysoul.runtime.events import EnvironmentEvent, EventKind
from tests.support.project import copy_initialized_project
from tinysoul.infra.time import CalendarDay
from tinysoul.infra.clock import BusinessClock
from tinysoul.plugins.memory import MemoryLink


class _LLM:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[TaskCall] = []
        calls = (
            ToolCallRecord("select", "select_action_domains", {"domains": ["core"]}, ToolKind.CONTROL),
            ToolCallRecord("answer", "core.answer", {"guide_blocks": [{"text": "answer"}]}, ToolKind.ACTION),
        )
        self.results = deque([
            *(TaskResult.success(raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
                                 answer=None, tool_calls=(call,)) for call in calls),
            TaskResult.success(raw_response=RawResponse("{}", "fake", "fake"),
                               answer=JsonAnswer({"text": "done"}), tool_calls=()),
        ])

    async def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        self.started.set()
        await self.release.wait()
        return self.results.popleft()


class _Clock:
    value = datetime(2026, 9, 15, 12, tzinfo=ZoneInfo("Asia/Shanghai"))

    def now(self):
        return self.value

    def today(self):
        return CalendarDay(self.value.date())


async def _create(root: Path, llm: _LLM, *, capacity: int = 1,
                  inbox_limits: InboxLimits = InboxLimits(), clock: BusinessClock | None = None) -> Agent:
    root = root / "project"
    copy_initialized_project(root)

    async def factory() -> AgentAssembly:
        builder = (AgentBuilder(root)
                   .with_config_environment(ConfigEnvironment.from_project_root(root, env={}))
                   .with_agent_settings(AgentSettings(interactive=False))
                   .with_llm_runner(llm))
        if clock is not None:
            builder.with_business_clock(clock)
        return await builder.build()

    return await Agent.assemble(factory, queue_capacity=capacity, inbox_limits=inbox_limits)


async def test_create_is_inactive_and_waiter_cancellation_preserves_real_turn(tmp_path: Path) -> None:
    llm = _LLM()
    agent = await _create(tmp_path, llm, inbox_limits=InboxLimits(capacity=1))
    assert agent.state is AgentState.CREATED and not llm.started.is_set()
    output = agent.subscribe(ObservationFilter(names=("turn.output",)))
    with pytest.raises(AgentClosedError):
        await agent.submit_turn(UserTurnRequest("before start"))
    await agent.start()
    try:
        handle = await agent.submit_turn(UserTurnRequest("hello", request_id="stable"))
        await agent.append_input(handle.turn_id, "queued input", input_id="input")
        with pytest.raises(InboxCapacityError):
            await agent.append_input(handle.turn_id, "over capacity", input_id="excess")
        assert await agent.submit_turn(handle.request) is handle
        await asyncio.wait_for(llm.started.wait(), 3)
        waiter = asyncio.create_task(handle.wait())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert not handle.done
        llm.release.set()
        result = await asyncio.wait_for(handle.wait(), 5)
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.answered
        assert result.outcome.context_completion is not None
        assert result.outcome.context_completion.turn_id == handle.turn_id
        observed = await asyncio.wait_for(anext(output), 1)
        assert isinstance(observed, ObservationRecord)
        assert observed.event.payload["text"] == "done"
        assert [item.text for item in result.outcome.context_completion.inputs] == ["hello", "queued input"]
        assert tuple((tmp_path / "project" / "runtime" / "session").rglob("turns/*.json"))
    finally:
        assert await agent.shutdown() == ()


async def test_cancel_active_turn_keeps_dispatcher_and_queued_work_alive(tmp_path: Path) -> None:
    llm = _LLM()
    agent = await _create(tmp_path, llm)
    await agent.start()
    try:
        active = await agent.submit_turn(UserTurnRequest("one"))
        await asyncio.wait_for(llm.started.wait(), 3)
        queued = await agent.submit_turn(UserTurnRequest("two"))
        with pytest.raises(AgentQueueFullError):
            await agent.submit_turn(UserTurnRequest("three"))
        assert await agent.cancel_turn(active.turn_id)
        assert (await asyncio.wait_for(active.wait(), 5)).state is TurnState.CANCELLED
        assert agent.state is AgentState.RUNNING
        llm.release.set()
        result = await asyncio.wait_for(queued.wait(), 5)
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.answered
    finally:
        await agent.shutdown()


async def test_config_save_keeps_live_services_until_explicit_reload(tmp_path: Path) -> None:
    agent = await _create(tmp_path, _LLM())
    await agent.start()
    try:
        previous = agent.services.get(WorkspaceEngine)
        saved = await agent.patch_config((ConfigMutation(
            source_id="project:configs/action/routing.toml",
            path="action.llm_action.timeout_seconds", op="set", value=30.0,
        ),))
        assert saved["state"] == "saved" and saved["pending_reload"] is True
        assert agent.services.get(WorkspaceEngine) is previous
        activated = await agent.reload_config()
        assert activated["state"] == "active"
        assert agent.services.get(WorkspaceEngine) is not previous
    finally:
        await agent.shutdown()


async def test_shutdown_settles_active_and_queued_handles_before_restart(tmp_path: Path) -> None:
    llm = _LLM()
    agent = await _create(tmp_path, llm)
    await agent.start()
    active = await agent.submit_turn(UserTurnRequest("one"))
    old_stream = agent.subscribe(ObservationFilter(names=("not_emitted",)))
    await asyncio.wait_for(llm.started.wait(), 3)
    queued = await agent.submit_turn(UserTurnRequest("two"))
    await agent.restart()
    try:
        assert (await active.wait()).state is TurnState.CANCELLED
        assert (await queued.wait()).state is TurnState.CANCELLED
        assert agent.state is AgentState.RUNNING
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(old_stream), 1)
    finally:
        await agent.shutdown()


async def test_memory_reflection_uses_current_workbench_and_dated_read_only_sources(tmp_path: Path) -> None:
    clock = _Clock()
    root = tmp_path / "project"
    copy_initialized_project(root)
    llm = _LLM()
    llm.release.set()
    builder = (AgentBuilder(root)
               .with_config_environment(ConfigEnvironment.from_project_root(root, env={}))
               .with_agent_settings(AgentSettings(interactive=False))
               .with_business_clock(clock).with_llm_runner(llm))
    agent = await Agent.assemble(builder.build)
    await agent.start()
    try:
        user = await agent.submit_turn(UserTurnRequest("Remember this discussion"))
        assert (await user.wait()).state is TurnState.FINISHED
        clock.value = datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        for call in (
            ToolCallRecord("select_memory", "select_action_domains", {"domains": ["memory_reflection"]}, ToolKind.CONTROL),
            ToolCallRecord("write_daily", "memory_reflection.write_daily", {"markdown": "A discussion was completed."}, ToolKind.ACTION),
        ):
            llm.results.append(TaskResult.success(
                raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
                answer=None, tool_calls=(call,),
            ))
        llm.results.extend(_LLM().results)
        handle = await agent.submit_turn(ReflectionRequest(
            scope=ReflectionScope.MEMORY, trigger=ReflectionTrigger.MANUAL,
            target_day=CalendarDay.parse("2026-09-15"),
        ))
        result = await asyncio.wait_for(handle.wait(), 10)
        assert isinstance(result.outcome, ReflectionOutcome)
        turn = next(task.turn_outcome for task in result.outcome.tasks if task.turn_outcome is not None)
        assert turn.status.value == "completed", turn.failure
        assert str(turn.business_day) == "2026-09-16"
        assert turn.context_completion is not None
        assert turn.context_completion.turn_id == handle.turn_id
        segments = turn.context_completion.segments
        session, archived = segments["session"], segments["workspace_archive"]
        assert isinstance(session, dict) and session["day"] == "2026-09-15"
        assert isinstance(archived, dict) and archived["source_day"] == "2026-09-15"
        assert (root / "memory" / MemoryLink.daily(CalendarDay.parse("2026-09-15").value).relative_path).is_file()
        assert not tuple((root / "runtime" / "session").rglob("turns/*.json"))
    finally:
        await agent.shutdown()


async def test_question_reply_resumes_same_turn_and_keeps_new_root_queued(tmp_path: Path) -> None:
    llm = _LLM()
    for call in reversed((
        ToolCallRecord("select_question", "select_action_domains", {"domains": ["core"]}, ToolKind.CONTROL),
        ToolCallRecord("ask", "core.ask", {"text": "Choose a direction", "options": ["A", "B"]}, ToolKind.ACTION),
    )):
        llm.results.appendleft(TaskResult.success(
            raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)), answer=None, tool_calls=(call,),
        ))
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
        await agent.append_input(active.turn_id, "additional context", input_id="extra")
        assert (await agent.publish(EnvironmentEvent(EventKind.EVENT, {"changed": True}, "e"))).delivered
        assert not (await agent.publish(EnvironmentEvent(EventKind.EVENT, {}, "stale", "previous_turn"))).delivered
        with pytest.raises(InboxClosedError):
            await agent.reply(active.turn_id, "old_question", "no")
        assert len(llm.calls) == 2 and queued.state is TurnState.QUEUED
        await agent.cancel_turn(queued.turn_id)
        receipt = await agent.reply(active.turn_id, question.question_id, "A")
        duplicate = await agent.reply(active.turn_id, question.question_id, "A")
        assert receipt.accepted and not duplicate.accepted
        result = await asyncio.wait_for(active.wait(), 5)
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.answered
        assert result.outcome.business_day == CalendarDay.parse("2026-09-15")
        completion = result.outcome.context_completion
        assert completion is not None
        reply = completion.inputs[-1]
        assert reply.text == "A" and reply.input_id == receipt.record_id
        assert reply.reply_to == question.question_id
        assert (await queued.wait()).state is TurnState.CANCELLED
        llm.results.extend(_LLM().results)
        following = await agent.submit_turn(UserTurnRequest("new day"))
        new_result = await asyncio.wait_for(following.wait(), 5)
        assert isinstance(new_result.outcome, TurnOutcome)
        assert new_result.outcome.business_day == CalendarDay.parse("2026-09-16")
        assert tuple((tmp_path / "project" / "archive").glob("*/session/turns/*.json"))
    finally:
        await agent.shutdown()


async def test_home_reflection_waits_and_retains_full_turn_without_user_session(tmp_path: Path) -> None:
    llm = _LLM()
    for call in reversed((
        ToolCallRecord("select_question", "select_action_domains", {"domains": ["core"]}, ToolKind.CONTROL),
        ToolCallRecord("ask", "core.ask", {"text": "Keep this preference?"}, ToolKind.ACTION),
    )):
        llm.results.appendleft(TaskResult.success(
            raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)), answer=None, tool_calls=(call,),
        ))
    llm.release.set()
    agent = await _create(tmp_path, llm)
    root = tmp_path / "project"
    home = AgentHomeEngineBuilder(AgentHomeSettings(
        original_root=root / "home", runtime_root=root / "runtime" / "home",
    )).build()
    home.write_top("home:agent@preference", "Use concise explanations.")
    await agent.start()
    try:
        handle = await agent.submit_turn(ReflectionRequest(
            scope=ReflectionScope.HOME, trigger=ReflectionTrigger.MANUAL,
        ))
        async with asyncio.timeout(4):
            while handle.wait_reason is not WaitReason.INPUT:
                assert not handle.done
                await asyncio.sleep(0.01)
        question = handle.question
        assert question is not None
        with pytest.raises(ConfigError) as busy:
            await agent.reload_config()
        assert busy.value.key == "config.activation_unavailable"
        await agent.reply(handle.turn_id, question.question_id, "Keep it")
        result = await asyncio.wait_for(handle.wait(), 5)
        assert isinstance(result.outcome, ReflectionOutcome)
        assert result.outcome.status is ReflectionStatus.COMPLETED
        turn = result.outcome.tasks[-1].turn_outcome
        assert turn is not None and turn.context_completion is not None
        assert turn.context_completion.inputs[-1].reply_to == question.question_id
        assert result.outcome.to_json()["tasks"]
        assert not tuple((root / "runtime" / "session").rglob("turns/*.json"))
    finally:
        await agent.shutdown()
