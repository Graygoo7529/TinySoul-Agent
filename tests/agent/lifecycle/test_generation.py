from __future__ import annotations
import asyncio
from pathlib import Path
import pytest
from tinysoul.agent import (
    AgentClosedError,
    AgentServiceStaleError,
    AgentState,
    UserTurnRequest,
)
from tinysoul.agent.composition.builder import AgentBuilder
from tinysoul.infra.config import ConfigError, ConfigMutation
from tinysoul.kernel.loop.outcomes import TurnOutcomeStatus
from tinysoul.plugins.workspace.services import WorkspaceService
from tests.agent.support import (
    _LLM,
    _create,
)

pytestmark = pytest.mark.integration


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
                    source_id="project-document:action.catalog:configs/action/catalog/core/actions/answer.toml",
                    path="runtime.timeout_seconds",
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
