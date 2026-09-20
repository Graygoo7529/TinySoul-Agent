from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import deque
from pathlib import Path

import pytest

from tinysoul.agent import (
    Agent,
    AgentClosedError,
    AgentQueueFullError,
    AgentState,
    TurnState,
    UserTurnRequest,
)
from tinysoul.agent import (
    InboxLimits,
    InboxCapacityError,
    ObservationFilter,
    ObservationRecord,
)
from tinysoul.agent.config import AgentSettings
from tinysoul.agent.composition.assembly import AgentAssembly
from tinysoul.agent.composition.builder import AgentBuilder
from tinysoul.infra.config import ConfigEnvironment, ConfigMutation, ConfigError
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.plugins.home import AgentHomeEngineBuilder, AgentHomeSettings
from tinysoul.plugins.reflection import (
    ReflectionRequest,
    ReflectionScope,
    ReflectionTrigger,
    ReflectionOutcome,
    ReflectionStatus,
)
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.messages import JsonPart
from tinysoul.llm.protocol.responses import JsonAnswer, RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.agent import RequestFailure
from tinysoul.agent import AgentServiceStaleError, HomeService
from tinysoul.kernel.registration import RegistrationError
from tinysoul.plugins.home.services import HomeReviewService
from tinysoul.plugins.memory.services import MemoryKnowledgeService
from tinysoul.plugins.memory import MemoryEngine
from tinysoul.kernel.loop.interaction.inbox import InboxClosedError, WaitReason
from tinysoul.runtime.events import EnvironmentEvent, EventKind
from tinysoul.runtime.sources import SourceState
from tests.support.project import copy_initialized_project
from tinysoul.infra.time import CalendarDay
from tinysoul.infra.json import JsonObject
from tinysoul.infra.process import (
    ManagedProcess,
    ManagedProcessRequest,
    ManagedProcessRunner,
)
from tinysoul.infra.clock import CalendarClock
from tinysoul.plugins.memory import MemoryLink


class _LLM:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[TaskCall] = []
        calls = (
            ToolCallRecord(
                "select",
                "select_action_domains",
                {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "answer",
                "core.answer",
                {"guide_blocks": [{"text": "answer"}]},
                ToolKind.ACTION,
            ),
        )
        self.results = deque(
            [
                *(
                    TaskResult.success(
                        raw_response=RawResponse(
                            "", "fake", "fake", tool_calls=(call,)
                        ),
                        answer=None,
                        tool_calls=(call,),
                    )
                    for call in calls
                ),
                TaskResult.success(
                    raw_response=RawResponse("{}", "fake", "fake"),
                    answer=JsonAnswer({"text": "done"}),
                    tool_calls=(),
                ),
            ]
        )

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


@pytest.mark.parametrize("origin", ("external", "sdk"))
async def test_workspace_change_resumes_same_turn_with_current_model_state(tmp_path: Path, origin: str) -> None:
    llm = _LLM()
    for call in reversed((
        ToolCallRecord("select_wait", "select_action_domains", {"domains": ["core"]}, ToolKind.CONTROL),
        ToolCallRecord("wait", "core.wait", {"topic": "workspace.changed"}, ToolKind.ACTION),
    )):
        llm.results.appendleft(TaskResult.success(
            raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)), answer=None,
            tool_calls=(call,),
        ))
    llm.release.set()
    agent = await _create(tmp_path, llm)
    await agent.start()
    try:
        active = await agent.submit_turn(UserTurnRequest("Wait for a resource"))
        async with asyncio.timeout(5):
            while active.wait_reason is not WaitReason.EVENT:
                assert not active.done
                await asyncio.sleep(0.01)
        if origin == "external":
            (tmp_path / "project/runtime/workspace/new.md").write_text("private resource body", encoding="utf-8")
        else:
            await agent.services.get(WorkspaceService).write_text("workspace:new.md", "private resource body")
        result = await asyncio.wait_for(active.wait(), 5)
        assert result.status is TurnOutcomeStatus.ANSWERED
        assert len(llm.calls) == 5
        state = next(message for message in llm.calls[2].messages.messages if message.label == "workspace")
        part = state.parts[0]
        assert isinstance(part, JsonPart)
        assert "workspace:new.md" in str(part.value)
        assert "private resource body" not in str(part.value)
    finally:
        await agent.shutdown()


async def test_watcher_binding_survives_rejected_reload_and_changes_on_success(tmp_path: Path) -> None:
    llm = _LLM()
    agent = await _create(tmp_path, llm)
    assert all(item.state is SourceState.STOPPED for item in agent.status().sources)
    await agent.start()
    try:
        original = agent.services.get(WorkspaceService)
        active = await agent.submit_turn(UserTurnRequest("work"))
        await asyncio.wait_for(llm.started.wait(), 3)
        with pytest.raises(ConfigError):
            await agent.reload_config()
        assert next(item for item in agent.status().sources if item.source == "workspace.fswatch").state is SourceState.RUNNING
        llm.release.set()
        assert (await active.wait()).status is TurnOutcomeStatus.ANSWERED
        await agent.patch_config((ConfigMutation(
            source_id="project:configs/workspace.toml", path="workspace.watch.enabled",
            op="set", value=False,
        ),))
        await agent.reload_config()
        assert next(item for item in agent.status().sources if item.source == "workspace.fswatch").state is SourceState.DISABLED
        with pytest.raises(AgentServiceStaleError):
            await original.snapshot()
        await agent.services.get(WorkspaceService).write_text("workspace:after.md", "still writable")
    finally:
        await agent.shutdown()


async def test_source_start_failure_keeps_previous_generation_and_listener(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tinysoul.environment.errors import EnvironmentError
    from tinysoul.plugins.workspace.events import WorkspaceRuntime
    from tinysoul.runtime import RuntimeException
    from tinysoul.runtime.sources import EventSink

    agent = await _create(tmp_path, _LLM())
    await agent.start()
    original_start = WorkspaceRuntime.start
    reject_candidate = True

    async def start(source: WorkspaceRuntime, publish: EventSink) -> None:
        nonlocal reject_candidate
        if reject_candidate:
            reject_candidate = False
            raise EnvironmentError("Test candidate source could not start")
        await original_start(source, publish)

    monkeypatch.setattr(WorkspaceRuntime, "start", start)
    try:
        service = agent.services.get(WorkspaceService)
        with pytest.raises(RuntimeException) as failed:
            await agent.reload_config()
        assert failed.value.payload["source"] == "workspace.fswatch"
        assert failed.value.payload["error_type"] == "EnvironmentError"
        assert next(
            item for item in agent.status().sources
            if item.source == "workspace.fswatch"
        ).state is SourceState.RUNNING
        (tmp_path / "project/runtime/workspace/recovered.md").write_text(
            "observed by the original owner", encoding="utf-8"
        )
        async with asyncio.timeout(5):
            while not (await service.snapshot()).resources:
                await asyncio.sleep(0.01)
        assert (await service.inspect("workspace:recovered.md")).size > 0
    finally:
        await agent.shutdown()


async def _create(
    root: Path,
    llm: _LLM,
    *,
    capacity: int = 1,
    inbox_limits: InboxLimits = InboxLimits(),
    clock: CalendarClock | None = None,
) -> Agent:
    root = root / "project"
    copy_initialized_project(root)

    async def factory() -> AgentAssembly:
        builder = (
            AgentBuilder(root)
            .with_config_environment(ConfigEnvironment.from_project_root(root, env={}, overrides={"reflection.schedule.enabled": False}))
            .with_agent_settings(AgentSettings(interactive=False))
            .with_llm_runner(llm)
        )
        if clock is not None:
            builder.with_calendar_clock(clock)
        return await builder.build()

    return await Agent.assemble(
        factory, queue_capacity=capacity, inbox_limits=inbox_limits
    )


async def test_create_is_inactive_and_waiter_cancellation_preserves_real_turn(
    tmp_path: Path,
) -> None:
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
        assert [item.text for item in result.outcome.context_completion.inputs] == [
            "hello",
            "queued input",
        ]
        assert tuple(
            (tmp_path / "project" / "runtime" / "session").rglob("turns/*.json")
        )
    finally:
        assert await agent.shutdown() == ()


async def test_shutdown_joins_inflight_start_and_rejects_cached_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _create(tmp_path, _LLM())
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def activate(assembly: AgentAssembly) -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    monkeypatch.setattr(AgentAssembly, "activate", activate)
    starting = asyncio.create_task(agent.start())
    await asyncio.wait_for(entered.wait(), 3)
    first, second = await asyncio.wait_for(
        asyncio.gather(agent.shutdown(), agent.shutdown()), 5
    )
    assert first == second == ()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert cleaned.is_set() and agent.state is AgentState.STOPPED
    assert await agent.shutdown() == ()


async def test_sdk_completed_facts_are_inspectable_until_daily_archive(tmp_path: Path) -> None:
    llm = _LLM()
    llm.release.set()
    def result(call: ToolCallRecord) -> TaskResult:
        return TaskResult.success(raw_response=RawResponse("", "fake", "fake", tool_calls=(call,)),
                                  answer=None, tool_calls=(call,))
    select = ToolCallRecord("select", "select_action_domains", {"domains": ["core"]}, ToolKind.CONTROL)
    llm.results.extendleft(reversed((result(select), result(ToolCallRecord(
        "wait", "core.wait", {"event_kind": "event", "event_id": "wake"}, ToolKind.ACTION
    )))))
    clock = _Clock()
    agent = await _create(tmp_path, llm, clock=clock)
    await agent.start()
    try:
        first = await agent.submit_turn(UserTurnRequest("first request"))
        async with asyncio.timeout(5):
            while first.wait_reason is None:
                assert not first.done
                await asyncio.sleep(0.01)
        await agent.publish(EnvironmentEvent(EventKind.EVENT, {"notice": "event-marker"}, "wake"))
        await agent.append_input(first.turn_id, "additional evidence", input_id="extra")
        completed = await asyncio.wait_for(first.wait(), 5)
        assert isinstance(completed.outcome, TurnOutcome) and completed.outcome.answered
        llm.results.extend((result(select), result(ToolCallRecord(
            "inspect", "core.context.inspect", {"ref": f"session:turn/{first.turn_id}"}, ToolKind.ACTION
        )), *_LLM().results))
        second = await agent.submit_turn(UserTurnRequest("review the preceding work"))
        review = await asyncio.wait_for(second.wait(), 5)
        assert isinstance(review.outcome, TurnOutcome) and review.outcome.answered
        completion = review.outcome.context_completion
        assert completion is not None
        inspection = next(item for item in completion.trace.actions if item.call.action_name == "core.context.inspect")
        assert inspection.result is not None
        assert "additional evidence" in str(inspection.result.payload)
        assert "event-marker" in str(inspection.result.payload)
        # The next decision task receives the full result before pressure may fold it.
        from tinysoul.runtime import CyclePhase, RunLevel
        assert any(
            "event-marker" in str(call.messages)
            for call in llm.calls
            if (phase := call.scope.nearest(RunLevel.PHASE)) is not None
            and phase.name == CyclePhase.PHASE1.value
        )
        clock.value = datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        llm.results.extend(_LLM().results)
        following = await agent.submit_turn(UserTurnRequest("new day"))
        new = await asyncio.wait_for(following.wait(), 5)
        assert isinstance(new.outcome, TurnOutcome)
        assert new.outcome.active_day == clock.today()
        assert f"session:turn/{first.turn_id}" not in str(llm.calls[-3].messages)
        from tinysoul.plugins.session.records.store import SessionStore
        archive = next((tmp_path / "project" / "archive").glob("*/session"))
        archived = SessionStore(root=archive).load_record(f"session:turn/{first.turn_id}")
        assert any(item.ref.endswith("#input/1") for item in archived.timeline)
        assert "event-marker" in str(archived.notes)
    finally:
        await agent.shutdown()


async def test_restart_stopped_agent_and_old_commands_do_not_reopen(
    tmp_path: Path,
) -> None:
    agent = await _create(tmp_path, _LLM())
    await agent.start()
    commands = agent.commands
    await agent.shutdown()
    await agent.restart()
    try:
        assert agent.state is AgentState.RUNNING
        with pytest.raises(AgentClosedError):
            await commands.submit_turn(UserTurnRequest("old instance"))
    finally:
        await agent.shutdown()


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
        await agent.append_input(active.turn_id, "accepted before cancellation", input_id="accepted")
        assert await agent.cancel_turn(active.turn_id)
        cancelled = await asyncio.wait_for(active.wait(), 5)
        assert cancelled.status is TurnOutcomeStatus.CANCELLED
        assert isinstance(cancelled.outcome, TurnOutcome)
        facts = cancelled.outcome.context_completion
        assert facts is not None and facts.inputs[-1].input_id == "accepted"
        assert any(item.ref.endswith("#input/accepted") for item in facts.trace.timeline)
        assert active.state is TurnState.FINISHED
        assert agent.state is AgentState.RUNNING
        llm.release.set()
        result = await asyncio.wait_for(queued.wait(), 5)
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.answered
    finally:
        await agent.shutdown()


async def test_config_save_keeps_live_services_until_explicit_reload(
    tmp_path: Path,
) -> None:
    agent = await _create(tmp_path, _LLM())
    await agent.start()
    try:
        previous = agent.services.get(WorkspaceService)
        await previous.write_text("workspace:same.txt", "before reload")
        saved = await agent.patch_config(
            (
                ConfigMutation(
                    source_id="project:configs/action/routing.toml",
                    path="action.llm_action.timeout_seconds",
                    op="set",
                    value=30.0,
                ),
            )
        )
        assert saved["state"] == "saved" and saved["pending_reload"] is True
        assert agent.services.get(WorkspaceService) is previous
        activated = await agent.reload_config()
        assert activated["state"] == "active"
        assert agent.services.get(WorkspaceService) is not previous
        with pytest.raises(AgentServiceStaleError):
            await previous.write_text("workspace:stale.txt", "must not commit")
        with pytest.raises(AgentServiceStaleError):
            await previous.snapshot()
        current = agent.services.get(WorkspaceService)
        assert (await current.read_text("workspace:same.txt")).text == "before reload"
        assert not await current.write_target_exists("workspace:stale.txt")
    finally:
        await agent.shutdown()


async def test_failed_reload_preserves_acquired_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _create(tmp_path, _LLM())
    await agent.start()
    previous = agent.services.get(WorkspaceService)

    async def fail_candidate(*args, **kwargs):
        raise ConfigError("Candidate cannot be built", key="candidate")

    monkeypatch.setattr(AgentBuilder, "_build_generation", fail_candidate)
    try:
        with pytest.raises(ConfigError):
            await agent.reload_config()
        assert agent.services.get(WorkspaceService) is previous
        await previous.write_text("workspace:still-active.txt", "valid")
        assert (await previous.read_text("workspace:still-active.txt")).text == "valid"
    finally:
        await agent.shutdown()


async def test_root_arriving_during_failed_activation_waits_without_blocking_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _LLM()
    llm.release.set()
    agent = await _create(tmp_path, llm)
    await agent.start()
    entered, release = asyncio.Event(), asyncio.Event()

    async def fail_candidate(*args, **kwargs):
        entered.set()
        await release.wait()
        raise ConfigError("Candidate failed", key="candidate")

    monkeypatch.setattr(AgentBuilder, "_build_generation", fail_candidate)
    reloading = asyncio.create_task(agent.reload_config())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        handle = await agent.submit_turn(UserTurnRequest("arrived during activation"))
        await asyncio.sleep(0)
        assert not llm.started.is_set() and not handle.done
        release.set()
        with pytest.raises(ConfigError):
            await asyncio.wait_for(reloading, 3)
        assert (
            await asyncio.wait_for(handle.wait(), 5)
        ).status is TurnOutcomeStatus.ANSWERED
    finally:
        release.set()
        await agent.shutdown()


async def test_sdk_local_write_is_joined_before_shutdown_releases_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event
    from tinysoul.plugins.workspace import WorkspaceEngine

    agent = await _create(tmp_path, _LLM())
    await agent.start()
    entered, release = asyncio.Event(), Event()
    loop, original = asyncio.get_running_loop(), WorkspaceEngine.write_text

    def write(owner, *args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        return original(owner, *args, **kwargs)

    monkeypatch.setattr(WorkspaceEngine, "write_text", write)
    service = agent.services.get(WorkspaceService)

    async def write_resource() -> None:
        await service.write_text("workspace:committed.txt", "persist")

    writing = asyncio.create_task(write_resource())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        writing.cancel()
        stopping = asyncio.create_task(agent.shutdown())
        await asyncio.sleep(0)
        assert not writing.done() and not stopping.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(writing, 4)
        await asyncio.wait_for(stopping, 4)
        assert (
            tmp_path / "project" / "runtime" / "workspace" / "committed.txt"
        ).read_text(encoding="utf-8") == "persist"
    finally:
        release.set()
        await agent.shutdown()


async def test_shutdown_joins_reload_candidate_before_closing_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = await _create(tmp_path, _LLM())
    await agent.start()
    service = agent.services.get(WorkspaceService)
    entered, release = asyncio.Event(), asyncio.Event()
    original = AgentBuilder._build_generation

    async def build_candidate(builder, *args, **kwargs):
        entered.set()
        await release.wait()
        return await original(builder, *args, **kwargs)

    monkeypatch.setattr(AgentBuilder, "_build_generation", build_candidate)
    reloading = asyncio.create_task(agent.reload_config())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        stopping = asyncio.create_task(agent.shutdown())
        await asyncio.sleep(0)
        assert agent.state is AgentState.STOPPING and not stopping.done()
        with pytest.raises(AgentClosedError):
            await service.write_text("workspace:closed.txt", "must not commit")
        release.set()
        assert (await asyncio.wait_for(reloading, 5))["state"] == "active"
        assert await asyncio.wait_for(stopping, 5) == ()
        assert agent.state is AgentState.STOPPED
        assert not (
            tmp_path / "project" / "runtime" / "workspace" / "closed.txt"
        ).exists()
    finally:
        release.set()
        await agent.shutdown()


async def test_day_bound_service_rejects_stale_write_and_restart_closes_old_services(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    agent = await _create(tmp_path, _LLM(), clock=clock)
    await agent.start()
    try:
        previous = agent.services.get(WorkspaceService)
        home = agent.services.get(HomeService)
        for facade in (HomeReviewService, MemoryKnowledgeService, MemoryEngine):
            with pytest.raises(RegistrationError):
                agent.services.get(facade)
        assert not hasattr(home, "resolve_review")
        await previous.write_text("workspace:same.txt", "old day")
        clock.value = datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        with pytest.raises(AgentServiceStaleError):
            await previous.write_text("workspace:same.txt", "wrong day", overwrite=True)
        current = agent.services.get(WorkspaceService)
        assert current is not previous
        assert not await current.write_target_exists("workspace:same.txt")
        await current.write_text("workspace:same.txt", "new day")
        assert (await current.read_text("workspace:same.txt")).text == "new day"
        await home.default_background_links()
        await agent.restart()
        with pytest.raises(AgentClosedError):
            await current.snapshot()
        with pytest.raises(AgentClosedError):
            await home.default_background_links()
        assert (
            await agent.services.get(WorkspaceService).read_text("workspace:same.txt")
        ).text == "new day"
    finally:
        await agent.shutdown()


async def test_shutdown_settles_active_and_queued_handles_before_restart(
    tmp_path: Path,
) -> None:
    llm = _LLM()
    agent = await _create(tmp_path, llm)
    await agent.start()
    active = await agent.submit_turn(UserTurnRequest("one"))
    old_stream = agent.subscribe(ObservationFilter(names=("not_emitted",)))
    await asyncio.wait_for(llm.started.wait(), 3)
    queued = await agent.submit_turn(UserTurnRequest("two"))
    await agent.restart()
    try:
        assert (await active.wait()).status is TurnOutcomeStatus.CANCELLED
        assert (await queued.wait()).status is RequestFailure.CANCELLED
        assert agent.state is AgentState.RUNNING
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(old_stream), 1)
    finally:
        await agent.shutdown()


@pytest.mark.parametrize("source", ("current", "archive", "daily_only"))
async def test_memory_reflection_revises_daily_from_fixed_target_sources(
    tmp_path: Path, source: str
) -> None:
    from tinysoul.plugins.memory import DailyMemoryDocument, MemorySettings

    clock = _Clock()
    root = tmp_path / "project"
    copy_initialized_project(root)
    target = CalendarDay.parse("2026-09-14" if source == "daily_only" else "2026-09-15")
    if source == "daily_only":
        seed = MemoryEngine(settings=MemorySettings(root=root / "memory"))
        seed.write_document(
            DailyMemoryDocument(
                day=target.value,
                created_on=target.value,
                updated_on=target.value,
                content="Morning notes.",
            )
        )
    llm = _LLM()
    llm.release.set()
    builder = (
        AgentBuilder(root)
        .with_config_environment(ConfigEnvironment.from_project_root(root, env={}, overrides={"reflection.schedule.enabled": False}))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_calendar_clock(clock)
        .with_llm_runner(llm)
    )
    agent = await Agent.assemble(builder.build)
    await agent.start()
    try:
        user = await agent.submit_turn(UserTurnRequest("Remember this discussion"))
        assert (await user.wait()).status is TurnOutcomeStatus.ANSWERED
        if source == "archive":
            clock.value = datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
        for index, trigger in enumerate(
            (ReflectionTrigger.MANUAL, ReflectionTrigger.SCHEDULED)
        ):
            content = (
                "Morning and afternoon, reorganized."
                if index == 0
                else "Morning revised, afternoon and evening."
            )
            calls = [
                ToolCallRecord(
                    "select_memory",
                    "select_action_domains",
                    {"domains": ["memory"]},
                    ToolKind.CONTROL,
                )
            ]
            if index or source == "daily_only":
                calls.extend(
                    (
                        ToolCallRecord(
                            "recall_daily",
                            "memory.recall",
                            {"memory_link": str(MemoryLink.daily(target.value))},
                            ToolKind.ACTION,
                        ),
                        ToolCallRecord(
                            "select_write",
                            "select_action_domains",
                            {"domains": ["memory"]},
                            ToolKind.CONTROL,
                        ),
                    )
                )
            calls.append(
                ToolCallRecord(
                    "write_daily",
                    "memory.write_daily",
                    {"markdown": content},
                    ToolKind.ACTION,
                )
            )
            for call in calls:
                llm.results.append(
                    TaskResult.success(
                        raw_response=RawResponse(
                            "", "fake", "fake", tool_calls=(call,)
                        ),
                        answer=None,
                        tool_calls=(call,),
                    )
                )
            llm.results.extend(_LLM().results)
            handle = await agent.submit_turn(
                ReflectionRequest(
                    scope=ReflectionScope.MEMORY,
                    trigger=trigger,
                    target_day=target,
                )
            )
            result = await asyncio.wait_for(handle.wait(), 10)
            assert isinstance(result.outcome, ReflectionOutcome)
            turn = next(
                task.turn_outcome
                for task in result.outcome.tasks
                if task.turn_outcome is not None
            )
            assert turn.status is TurnOutcomeStatus.COMPLETED, turn.failure
            assert turn.active_day == clock.today()
            assert turn.context_completion is not None
            segments = turn.context_completion.segments
            session = segments["session"]
            assert isinstance(session, dict) and session["day"] == str(target)
            if source == "archive":
                archived = segments["workspace_archive"]
                assert isinstance(archived, dict) and archived["source_day"] == str(
                    target
                )
            else:
                archived = segments["workspace_archive"]
                assert isinstance(archived, dict) and archived["source_day"] is None
            persisted = (
                root / "memory" / MemoryLink.daily(target.value).relative_path
            ).read_text(encoding="utf-8")
            assert content in persisted
        records = tuple((root / "runtime" / "session").rglob("turns/*.json"))
        assert len(records) == (0 if source == "archive" else 1)
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
                {"text": "Choose a direction", "options": ["A", "B"]},
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
                EnvironmentEvent(EventKind.EVENT, {"changed": True}, "e", active.turn_id)
            )
        ).delivered
        assert not (
            await agent.publish(
                EnvironmentEvent(EventKind.EVENT, {}, "stale", "previous_turn")
            )
        ).delivered
        with pytest.raises(InboxClosedError):
            await agent.reply(active.turn_id, "old_question", "no")
        assert len(llm.calls) == 2 and queued.state is TurnState.QUEUED
        await agent.cancel_turn(queued.turn_id)
        receipt = await agent.reply(active.turn_id, question.question_id, "A")
        duplicate = await agent.reply(active.turn_id, question.question_id, "A")
        assert receipt.accepted and not duplicate.accepted
        result = await asyncio.wait_for(active.wait(), 5)
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.answered
        assert result.outcome.active_day == CalendarDay.parse("2026-09-15")
        completion = result.outcome.context_completion
        assert completion is not None
        reply = completion.inputs[-1]
        assert reply.text == "A" and reply.input_id == receipt.record_id
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


async def test_execution_is_stopped_before_queued_next_day_work_can_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes: list[ManagedProcess] = []
    start = ManagedProcessRunner.start

    def capture(
        self: ManagedProcessRunner,
        request: ManagedProcessRequest,
        *,
        capture_root: Path | None = None,
    ) -> ManagedProcess:
        process = start(self, request, capture_root=capture_root)
        processes.append(process)
        return process

    monkeypatch.setattr(ManagedProcessRunner, "start", capture)
    llm = _LLM()
    for call in reversed(
        (
            ToolCallRecord(
                "select_execution",
                "select_action_domains",
                {"domains": ["execution"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "start",
                "execution.start",
                {
                    "interpreter": "python",
                    "source_link": "workspace:long.py",
                    "interactive": True,
                },
                ToolKind.ACTION,
            ),
            ToolCallRecord(
                "select_question",
                "select_action_domains",
                {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "ask", "core.ask", {"text": "Continue this job?"}, ToolKind.ACTION
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
        await agent.patch_config(
            (
                ConfigMutation(
                    source_id="project:configs/execution.toml",
                    path="execution.enabled",
                    op="set",
                    value=True,
                ),
                ConfigMutation(
                    source_id="project:configs/execution.toml",
                    path="execution.interpreters.python.executable",
                    op="set",
                    value=sys.executable,
                ),
            )
        )
        await agent.reload_config()
        workspace = agent.services.get(WorkspaceService)
        await workspace.write_text(
            "workspace:long.py",
            (
                "import subprocess,sys\n"
                "subprocess.Popen([sys.executable, '-c', "
                "\"import threading; from pathlib import Path; "
                "f = Path('old-day.txt').open('w', encoding='utf-8'); "
                "f.write('preserved'); f.flush(); threading.Event().wait(15)\"], "
                "stdin=subprocess.DEVNULL)\n"
                "sys.stdin.read()\n"
            ),
        )
        active = await agent.submit_turn(UserTurnRequest("run and wait"))
        root = tmp_path / "project"
        async with asyncio.timeout(8):
            while active.wait_reason is not WaitReason.INPUT or not tuple(
                (root / "runtime" / "workspace").rglob("old-day.txt")
            ):
                assert not active.done
                await asyncio.sleep(0.01)
        assert len(processes) == 1 and processes[0].running()
        clock.value = datetime(2026, 9, 16, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
        queued = await agent.submit_turn(UserTurnRequest("next day"))
        assert queued.state is TurnState.QUEUED
        assert (await workspace.read_text("workspace:long.py")).text
        await agent.cancel_turn(active.turn_id)
        cancelled = await asyncio.wait_for(active.wait(), 8)
        assert isinstance(cancelled.outcome, TurnOutcome)
        assert cancelled.outcome.status is TurnOutcomeStatus.CANCELLED
        next_result = await asyncio.wait_for(queued.wait(), 8)
        assert (
            isinstance(next_result.outcome, TurnOutcome)
            and next_result.outcome.answered
        )
        assert next_result.outcome.active_day == CalendarDay.parse("2026-09-16")
        assert not processes[0].running()
        assert not tuple((root / "runtime" / "workspace").rglob("old-day.txt"))
        artifacts = tuple((root / "archive").rglob("old-day.txt"))
        assert (
            len(artifacts) == 1
            and artifacts[0].read_text(encoding="utf-8") == "preserved"
        )
        with pytest.raises(AgentServiceStaleError):
            await workspace.snapshot()
    finally:
        await agent.shutdown()


async def test_home_reflection_waits_and_retains_full_turn_without_user_session(
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
                "ask", "core.ask", {"text": "Keep this preference?"}, ToolKind.ACTION
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
    agent = await _create(tmp_path, llm)
    root = tmp_path / "project"
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=root / "home",
            runtime_root=root / "runtime" / "home",
        )
    ).build()
    home.write_top("home:agent@preference", "Use concise explanations.")
    await agent.start()
    try:
        handle = await agent.submit_turn(
            ReflectionRequest(
                scope=ReflectionScope.HOME,
                trigger=ReflectionTrigger.MANUAL,
                instructions="Only review the requested communication preference.",
            )
        )
        assert await agent.submit_turn(handle.request) is handle
        async with asyncio.timeout(4):
            while handle.wait_reason is not WaitReason.INPUT:
                assert not handle.done
                await asyncio.sleep(0.01)
        question = handle.question
        assert question is not None
        assert any(
            "Only review the requested communication preference." in str(call)
            for call in llm.calls
        )
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


@pytest.mark.parametrize("wait_kind", ["event", "timer", "question"])
async def test_append_resumes_unified_wait_on_same_turn(
    tmp_path: Path, wait_kind: str
) -> None:
    llm = _LLM()
    action = "core.ask" if wait_kind == "question" else "core.wait"
    params: JsonObject = (
        {"text": "Choose"}
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
        await agent.cancel_turn(queued.turn_id)
        receipt = await agent.append_input(
            handle.turn_id, "Change direction", input_id="new"
        )
        result = await asyncio.wait_for(handle.wait(), 5)
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.answered
        completion = result.outcome.context_completion
        assert completion is not None and completion.turn_id == handle.turn_id
        assert completion.inputs[-1].input_id == receipt.record_id
        assert completion.inputs[-1].reply_to == ""
        if question is not None:
            with pytest.raises(AgentClosedError):
                await agent.reply(handle.turn_id, question.question_id, "late")
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
        assert not await agent.cancel_turn(handle.turn_id)
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
