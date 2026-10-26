from __future__ import annotations
import asyncio
from pathlib import Path
import pytest
from tests.support.project import create_test_project
from tinysoul.agent import (
    Agent,
    AgentClosedError,
    AgentState,
    InboxCapacityError,
    InboxLimits,
    ObservationFilter,
    ObservationRecord,
    RequestFailure,
    UserTurnRequest,
)
from tinysoul.agent.composition.assembly import AgentRuntime
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.plugins.workspace.services import WorkspaceService
from tests.agent.support import (
    _LLM,
    _create,
)

pytestmark = pytest.mark.integration


async def test_agent_wait_for_exit_survives_restart_and_detaches_cancelled_waiter(
    tmp_path: Path,
) -> None:
    llm = _LLM()
    llm.release.set()
    agent = await _create(tmp_path, llm)
    await agent.start()
    old_commands = agent.commands
    waiting = asyncio.create_task(agent.wait_for_exit())
    detached = asyncio.create_task(agent.wait_for_exit())
    try:
        await agent.restart()
        assert not waiting.done()
        detached.cancel()
        with pytest.raises(asyncio.CancelledError):
            await detached
        with pytest.raises(AgentClosedError):
            await old_commands.submit_turn(UserTurnRequest("old facade"))
        current = await agent.submit_turn(UserTurnRequest("new facade"))
        assert (await asyncio.wait_for(current.wait(), 5)).outcome is not None
        assert not waiting.done()
    finally:
        await agent.shutdown()
        await asyncio.gather(waiting, detached, return_exceptions=True)
    assert waiting.cancelled()


async def test_wait_for_exit_requires_start_and_retains_normal_exit(
    tmp_path: Path,
) -> None:
    from tinysoul.agent.requests import ExitRequest

    agent = await _create(tmp_path, _LLM())
    try:
        with pytest.raises(AgentClosedError):
            await agent.wait_for_exit()
        await agent.start()
        agent.commands.request_exit(ExitRequest(source="test", text="done"))
        result = await asyncio.wait_for(agent.wait_for_exit(), 5)
        assert agent.state is AgentState.STOPPED
        assert result.turn_count == 0 and result.transfer is not None
        await agent.shutdown()
        assert await agent.wait_for_exit() is result
    finally:
        await agent.shutdown()


@pytest.mark.parametrize("cancel_start", (False, True))
async def test_failed_start_settles_requests_accepted_by_sources(
    tmp_path: Path,
    cancel_start: bool,
) -> None:
    from tinysoul.runtime import RuntimeException

    root = tmp_path / "project"
    create_test_project(root)
    llm = _LLM()
    definition = (
        standard_agent(root)
        .with_config_environment(
            ConfigEnvironment.from_project_root(
                root,
                env={},
                overrides={
                    "agent.interactive": False,
                    "reflection.schedule.enabled": False,
                    "workspace.watch.enabled": False,
                },
            )
        )
        .with_llm_runner(llm)
        .build()
    )
    agent = await Agent.assemble(definition)
    assembly = agent.runtime
    entered, release = asyncio.Event(), asyncio.Event()
    source_stopped = False
    handles = []

    class SubmittingService:
        async def start(self) -> None:
            handles.append(
                await assembly.commands.submit_turn(UserTurnRequest("during startup"))
            )

        async def stop(self) -> None:
            nonlocal source_stopped
            source_stopped = True

    class FailingService:
        async def start(self) -> None:
            entered.set()
            await release.wait()
            raise RuntimeException("runtime.startup_failed", "private startup detail")

        async def stop(self) -> None:
            pass

    assembly.mount_service(SubmittingService())
    assembly.mount_service(FailingService())

    starting = asyncio.create_task(agent.start())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if cancel_start:
            await agent.shutdown()
        else:
            release.set()
        with pytest.raises(
            asyncio.CancelledError if cancel_start else RuntimeException
        ):
            await starting
        result = await asyncio.wait_for(handles[0].wait(), 5)
        assert result.request_failure is (
            RequestFailure.CANCELLED if cancel_start else RequestFailure.FAILED
        )
        assert result.error_type == (None if cancel_start else "RuntimeException")
        assert handles[0].cancel_requested is cancel_start
        assert result.outcome is None and not llm.calls
        assert source_stopped and assembly.generation_handle.closed
        assert not assembly.is_available
    finally:
        release.set()
        await agent.shutdown()
        await asyncio.gather(starting, return_exceptions=True)


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
        await agent.append_input(handle.request_id, "queued input", input_id="input")
        with pytest.raises(InboxCapacityError):
            await agent.append_input(
                handle.request_id, "over capacity", input_id="excess"
            )
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

    async def activate(runtime: AgentRuntime) -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    monkeypatch.setattr(AgentRuntime, "activate", activate)
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
