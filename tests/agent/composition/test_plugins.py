from __future__ import annotations
import asyncio
import sys
from dataclasses import replace
from pathlib import Path
import pytest
from tests.support.project import create_test_project
from tinysoul.agent import Agent, UserTurnRequest
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.agent.config import AgentSettings
from tinysoul.agent.errors import AgentClosedError, AgentServiceStaleError
from tinysoul.infra.config import ConfigEnvironment, ConfigError, ConfigMutation
from tinysoul.kernel.loop import LoopSettings, TurnSettings
from tinysoul.kernel.loop.assembly import TurnProfile
from tinysoul.kernel.loop.interaction.inbox import WaitReason
from tinysoul.kernel.loop.turn import TurnOutcome
from tinysoul.kernel.registration import RegistrationError
from tinysoul.kernel.retrieval.contracts import QuerySource, RetrievalRequest, TextQuery
from tinysoul.llm.protocol.messages import JsonPart, UserMessage
from tinysoul.llm.protocol.tools import ToolCallRecord, ToolKind
from tinysoul.plugins.home.services import HomeReviewService, HomeService
from tinysoul.plugins.memory.services import (
    MemoryKnowledgeService,
    MemoryReadService,
    MemoryService,
)
from tinysoul.plugins.reflection.builder import ReflectionBuilder
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RunLevel, RuntimeException
from tinysoul.runtime.events import EnvironmentEvent, EventKind
from tests.agent.composition.support import (
    FakeLLM,
    _ProbePlugin,
    _ProbeService,
    _text_result,
    _test_config,
    _tool_result,
)

pytestmark = pytest.mark.integration


async def test_three_scenarios_have_independent_policies_and_owner_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    create_test_project(root)
    profiles: list[TurnProfile] = []
    original = ReflectionBuilder.build

    def capture(builder):
        result = original(builder)
        profiles.extend(result.profiles)
        return result

    monkeypatch.setattr(ReflectionBuilder, "build", capture)
    config = ConfigEnvironment.from_project_root(
        root,
        env={},
        overrides={
            "capabilities.expand.servers.local.enabled": True,
            "capabilities.expand.servers.local.command": sys.executable,
            "capabilities.subagent.agents.local.enabled": True,
            "capabilities.subagent.agents.local.command": sys.executable,
        },
    )
    app = await (
        standard_agent(root)
        .with_config_environment(config)
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
        .build_runtime()
    )
    try:
        user = app.generation_handle.snapshot().generation.user_turn.profile
        home, memory = profiles
        identifiers = [
            {name for _, name in profile.action.action_identifiers()}
            for profile in (user, home, memory)
        ]
        assert "home.inspect" in identifiers[0]
        assert "home.diff" in identifiers[1] and "home.review" in identifiers[1]
        assert (
            "memory.write_daily" in identifiers[2] and "memory.write" in identifiers[2]
        )
        assert not identifiers[0].intersection(
            {"home.diff", "home.review", "memory.write", "memory.write_daily"}
        )
        assert "memory.memorize" not in identifiers[2]
        for actions in identifiers:
            assert {
                "expand.search",
                "expand.call",
                "subagent.connect",
                "subagent.delegate",
                "subagent.respond",
            } <= actions
        assert home.services.get(HomeReviewService)
        assert home.services.get(MemoryService)
        assert memory.services.get(MemoryKnowledgeService)
        assert memory.services.get(MemoryReadService)
        await user.services.get(HomeService).write_top(
            "home:top/agent/search-proof", "uniqueoverlayevidence"
        )
        assert not (root / "home/agent/search-proof.md").exists()
        for profile in (user, home, memory):
            service = profile.services.get(HomeService)
            page = await service.search(
                RetrievalRequest(
                    QuerySource("agent", TextQuery("uniqueoverlayevidence"))
                )
            )
            assert page.items[0].ref == "home:resource/agent/search-proof.md"
            assert "uniqueoverlayevidence" in str(
                (await service.inspect(page.items[0].ref)).to_json()
            )
        for profile, denied in (
            (user, HomeReviewService),
            (user, MemoryKnowledgeService),
            (home, MemoryKnowledgeService),
            (memory, HomeReviewService),
            (memory, MemoryService),
        ):
            with pytest.raises(RegistrationError):
                profile.services.get(denied)
    finally:
        await app.close()


async def test_probe_plugin_composes_config_segment_action_event_sdk_and_restart(
    tmp_path: Path,
) -> None:
    root = create_test_project(tmp_path / "project")
    config_path = root / "configs" / "capabilities" / "probe.toml"
    config_path.write_text("[capabilities.probe]\nvalue = 3\n", encoding="utf-8")
    plugin = _ProbePlugin()
    llm = FakeLLM(
        (
            _tool_result(
                ToolCallRecord(
                    id="select_1",
                    name="select_action_domains",
                    arguments={"domains": ["core"]},
                    kind=ToolKind.CONTROL,
                )
            ),
            _tool_result(
                ToolCallRecord(
                    id="wait_1",
                    name="core.wait",
                    arguments={
                        "event_kind": "event",
                        "topic": "probe.changed",
                        "source": "host",
                    },
                    kind=ToolKind.ACTION,
                )
            ),
            _tool_result(
                ToolCallRecord(
                    id="select_2",
                    name="select_action_domains",
                    arguments={"domains": ["core"]},
                    kind=ToolKind.CONTROL,
                )
            ),
            _tool_result(
                ToolCallRecord(
                    id="answer_1",
                    name="core.answer",
                    arguments={"guide_blocks": [{"text": "answer"}]},
                    kind=ToolKind.ACTION,
                )
            ),
            _text_result("done"),
        )
    )
    assembly = (
        standard_agent(root)
        .with_config_environment(ConfigEnvironment.from_project_root(root, env={}))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=3)))
        .with_llm_runner(llm)
        .use(plugin)
        .build()
    )
    assert plugin.owners == []
    agent = await Agent.assemble(assembly)
    assert len(plugin.owners) == 1
    try:
        await agent.start()
        original_runtime = agent.runtime
        generation = original_runtime.generation_handle.snapshot().generation
        original_profile = generation.user_turn.profile
        for profile in generation.reflection_profiles:
            with pytest.raises(RegistrationError):
                profile.services.get(_ProbeService)
            assert not any(
                item.filter.topic == "probe.changed" for item in profile.events
            )
        old_service = agent.services.get(_ProbeService)
        assert await old_service.read() == 3
        handle = await agent.submit_turn(UserTurnRequest("wait"))
        async with asyncio.timeout(5):
            while handle.wait_reason is not WaitReason.EVENT:
                assert not handle.done
                await asyncio.sleep(0.01)
        receipt = await agent.publish(
            EnvironmentEvent(
                EventKind.EVENT, {"value": 8}, topic="probe.changed", source="host"
            )
        )
        assert receipt.delivered
        result = await asyncio.wait_for(handle.wait(), 5)
        assert isinstance(result.outcome, TurnOutcome) and result.outcome.answered
        owner = plugin.owners[0]
        assert owner.events == [8]
        assert owner.actions == ["core.answer"]
        from tinysoul.runtime import CyclePhase

        assert [
            part.value
            for call in llm.calls
            if (phase := call.scope.nearest(RunLevel.PHASE)) is not None
            and phase.name == CyclePhase.PHASE1.value
            for message in call.messages.messages
            if isinstance(message, UserMessage) and message.label == "probe"
            for part in message.parts
            if isinstance(part, JsonPart)
        ] == [{"value": 3}, {"value": 8}]
        completion = result.outcome.context_completion
        assert completion is not None
        assert completion.segments["probe_state"] == {"value": 8}
        answer = next(
            item
            for item in completion.trace.actions
            if item.call.action_name == "core.answer"
        )
        assert answer.result is not None and answer.result.payload["text"] == "done"
        assert owner.lifecycle == ["prepare", "release", "synchronize", "complete"]

        with pytest.raises(ConfigError) as invalid:
            await agent.patch_config(
                (
                    ConfigMutation(
                        "project:configs/capabilities/probe.toml",
                        "capabilities.probe.value",
                        "set",
                        "invalid",
                    ),
                )
            )
        assert invalid.value.key == "capabilities.probe.value"
        await agent.patch_config(
            (
                ConfigMutation(
                    "project:configs/capabilities/probe.toml",
                    "capabilities.probe.value",
                    "set",
                    5,
                ),
            )
        )
        assert await old_service.read() == 8
        await agent.reload_config()
        assert agent.runtime is original_runtime
        assert owner.closed == 1 and len(plugin.owners) == 2
        with pytest.raises(AgentServiceStaleError):
            await old_service.read()
        reloaded_service = agent.services.get(_ProbeService)
        assert await reloaded_service.read() == 5
        assert original_profile.services.get(_ProbeService) is not reloaded_service
        old_commands = agent.commands
        await agent.restart()
        assert (
            agent.runtime is not original_runtime and not original_runtime.is_available
        )
        assert len(plugin.owners) == 3
        with pytest.raises(AgentClosedError):
            await reloaded_service.read()
        with pytest.raises(AgentClosedError):
            await old_commands.submit_turn(UserTurnRequest("retired runtime"))
        assert await agent.services.get(_ProbeService).read() == 5
    finally:
        await agent.shutdown()
    assert all(owner.closed == 1 for owner in plugin.owners)


@pytest.mark.parametrize(
    "section", ["loop", "loop.extra", "reflection.extra", "capabilities"]
)
def test_builder_rejects_configuration_owner_collision_before_materializing(
    tmp_path: Path,
    section: str,
) -> None:
    plugin = _ProbePlugin()
    plugin.configuration = (replace(plugin.configuration[0], section=section),)
    with pytest.raises(RegistrationError, match="overlap"):
        standard_agent(tmp_path).use(plugin).build()
    assert plugin.owners == []


def test_probe_configuration_failure_uses_its_owner_bridge(tmp_path: Path) -> None:
    plugin = _ProbePlugin()
    with pytest.raises(RuntimeException) as caught:
        (
            standard_agent(tmp_path)
            .with_config_environment(
                _test_config(tmp_path, {"capabilities.probe.value": "invalid"})
            )
            .with_llm_runner(FakeLLM(()))
            .use(plugin)
            .build()
        )
    assert caught.value.reason == RUNTIME_STARTUP_FAILED
    assert caught.value.payload["module"] == "probe"
    assert caught.value.payload["kind"] == "probe.configuration_failed"
    assert caught.value.payload["key"] == "capabilities.probe.value"
    assert plugin.owners == []
