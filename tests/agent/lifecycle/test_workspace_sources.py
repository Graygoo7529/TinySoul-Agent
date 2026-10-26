from __future__ import annotations
import asyncio
from pathlib import Path
import pytest
from tinysoul.agent import AgentServiceStaleError, UserTurnRequest
from tinysoul.infra.config import ConfigError, ConfigMutation
from tinysoul.kernel.loop.interaction.inbox import WaitReason
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.llm.protocol.messages import TextPart
from tinysoul.llm.protocol.responses import RawResponse, TaskResult
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.plugins.workspace.services import WorkspaceService
from tinysoul.runtime.sources import SourceState
from tests.agent.support import (
    _LLM,
    _create,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("origin", ("external", "sdk"))
async def test_workspace_change_resumes_same_turn_with_current_model_state(
    tmp_path: Path, origin: str
) -> None:
    llm = _LLM()
    for call in reversed(
        (
            ToolCallRecord(
                "select_wait",
                "select_action_domains",
                {"domains": ["core"]},
                ToolKind.CONTROL,
            ),
            ToolCallRecord(
                "wait", "core.wait", {"topic": "workspace.changed"}, ToolKind.ACTION
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
    agent = await _create(tmp_path, llm, watch_workspace=origin == "external")
    await agent.start()
    try:
        active = await agent.submit_turn(UserTurnRequest("Wait for a resource"))
        async with asyncio.timeout(5):
            while active.wait_reason is not WaitReason.EVENT:
                assert not active.done
                await asyncio.sleep(0.01)
        if origin == "external":
            (tmp_path / "project/runtime/workspace/new.md").write_text(
                "private resource body", encoding="utf-8"
            )
        else:
            await agent.services.get(WorkspaceService).write_text(
                "workspace:new.md", "private resource body"
            )
        result = await asyncio.wait_for(active.wait(), 5)
        assert result.status is TurnOutcomeStatus.ANSWERED
        assert len(llm.calls) == 5
        state = next(
            message
            for message in llm.calls[2].messages.messages
            if message.label == "workspace"
        )
        part = state.parts[0]
        assert isinstance(part, TextPart)
        assert "workspace:new.md" in part.text
        assert "private resource body" not in part.text
    finally:
        await agent.shutdown()


async def test_watcher_binding_survives_rejected_reload_and_changes_on_success(
    tmp_path: Path,
) -> None:
    llm = _LLM()
    agent = await _create(tmp_path, llm, watch_workspace=True)
    assert all(item.state is SourceState.STOPPED for item in agent.status().sources)
    await agent.start()
    try:
        original = agent.services.get(WorkspaceService)
        active = await agent.submit_turn(UserTurnRequest("work"))
        await asyncio.wait_for(llm.started.wait(), 3)
        with pytest.raises(ConfigError):
            await agent.reload_config()
        assert (
            next(
                item
                for item in agent.status().sources
                if item.source == "workspace.fswatch"
            ).state
            is SourceState.RUNNING
        )
        llm.release.set()
        assert (await active.wait()).status is TurnOutcomeStatus.ANSWERED
        await agent.patch_config(
            (
                ConfigMutation(
                    source_id="project:configs/workspace.toml",
                    path="workspace.watch.enabled",
                    op="set",
                    value=False,
                ),
            )
        )
        await agent.reload_config()
        assert (
            next(
                item
                for item in agent.status().sources
                if item.source == "workspace.fswatch"
            ).state
            is SourceState.DISABLED
        )
        with pytest.raises(AgentServiceStaleError):
            await original.snapshot()
        await agent.services.get(WorkspaceService).write_text(
            "workspace:after.md", "still writable"
        )
    finally:
        llm.release.set()
        await agent.shutdown()


async def test_source_start_failure_keeps_previous_generation_and_listener(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tinysoul.environment.errors import EnvironmentError
    from tinysoul.plugins.workspace.events import WorkspaceRuntime
    from tinysoul.runtime import RuntimeException
    from tinysoul.runtime.sources import EventSink

    agent = await _create(tmp_path, _LLM(), watch_workspace=True)
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
        assert (
            next(
                item
                for item in agent.status().sources
                if item.source == "workspace.fswatch"
            ).state
            is SourceState.RUNNING
        )
        (tmp_path / "project/runtime/workspace/recovered.md").write_text(
            "observed by the original owner", encoding="utf-8"
        )
        async with asyncio.timeout(5):
            while not (await service.snapshot()).resources:
                await asyncio.sleep(0.01)
        assert (await service.stat("workspace:recovered.md")).size > 0
    finally:
        await agent.shutdown()
