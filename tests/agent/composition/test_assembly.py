from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from tinysoul.agent.composition.activity import AgentTurnActivity
from tinysoul.infra.concurrency import CleanupDiagnostic
from tinysoul.kernel.context import ContextEngineBuilder
from tinysoul.kernel.jobs import JobRegistry
from tinysoul.kernel.registration import (
    GenerationBuildContext,
    PluginGeneration,
    PluginProfileExtension,
    PluginRegistry,
    PluginTurnResource,
    TurnResourceStage,
)
from tinysoul.agent.composition.builder import standard_agent
from tinysoul.kernel.loop.phases import LLMRunner
from tinysoul.llm.adapter.registry import ProviderRegistry
from tinysoul.llm.protocol.messages import MessageStack, UserMessage
from tinysoul.llm.protocol.requests import CallSettings, ModelContextOverflowPolicy, TaskCall
from tests.llm.execution.support import FakeProvider
from tinysoul.plugins.reflection import ReflectionAvailability
from tests.agent.composition.support import FakeLLM, _test_config


@pytest.mark.integration
async def test_context_window_limit_reaches_the_shared_llm_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RunnerConsumer:
        id = "runner_consumer"
        provides = requires = configuration = model_uses = search_capabilities = ()
        runner: LLMRunner | None = None

        async def build_generation(self, context: GenerationBuildContext) -> PluginGeneration:
            self.runner = context.llm
            return PluginGeneration(self.id)

    provider = FakeProvider(provider_id="test")

    async def providers(*args: object, **kwargs: object) -> ProviderRegistry:
        return ProviderRegistry([provider])

    monkeypatch.setattr("tinysoul.agent.composition.builder.build_provider_registry", providers)
    consumer = RunnerConsumer()
    app = await (
        standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path, {"context.max_window_tokens": 100}))
        .use(consumer)
        .build()
        .build_runtime()
    )
    try:
        assert consumer.runner is not None
        result = await consumer.runner.invoke(TaskCall(
            profile="llm-action",
            messages=MessageStack.of(UserMessage.from_text("x" * 100)),
            settings=CallSettings(max_output_tokens=10),
            context_overflow_policy=ModelContextOverflowPolicy.RETURN_FAILURE,
        ))
        assert result.failure is not None and result.failure.reason.value == "input_capacity"
        assert provider.calls == []
    finally:
        await app.close()


async def test_turn_resources_release_jobs_before_sessions_and_synchronization() -> (
    None
):
    order: list[str] = []

    class Jobs(JobRegistry):
        async def cleanup_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
            order.append("jobs")
            return await super().cleanup_turn(turn_id)

    class Resource:
        def __init__(self, name: str) -> None:
            self.name = name

        async def close_turn(self, turn_id: str) -> tuple[CleanupDiagnostic, ...]:
            order.append(self.name)
            return ()

    resolved = PluginRegistry(
        (
            PluginProfileExtension(
                "probe",
                turn_resources=(
                    PluginTurnResource(
                        Resource("workspace"), TurnResourceStage.SYNCHRONIZE
                    ),
                    PluginTurnResource(Resource("session"), TurnResourceStage.RELEASE),
                ),
            ),
        )
    ).resolve(ContextEngineBuilder(system_text="identity").build())
    activity = AgentTurnActivity(Jobs(), resolved.turn_resources)
    assert await activity.cleanup_turn("turn") == ()
    assert order == ["jobs", "session", "workspace"]


@dataclass
class _RecordingService:
    started: int = 0
    stopped: int = 0
    fail_start: bool = False
    fail_stop: bool = False

    async def start(self) -> None:
        self.started += 1
        if self.fail_start:
            raise RuntimeError("start failed")

    async def stop(self) -> None:
        self.stopped += 1
        if self.fail_stop:
            raise RuntimeError("stop failed")


@pytest.mark.integration
async def test_host_services_start_after_preparation_and_close(tmp_path: Path) -> None:
    app = await (standard_agent(tmp_path)
                 .with_config_environment(_test_config(tmp_path))
                 .with_llm_runner(FakeLLM(())).build().build_runtime())
    service = _RecordingService()
    app.mount_service(service)
    try:
        await app.activate()
        availability = app.generation_handle.snapshot().generation.reflection.availability()
        assert isinstance(availability, ReflectionAvailability)
        assert service.started == 1 and app.is_available
    finally:
        await app.close()
    assert service.stopped == 1


@pytest.mark.integration
async def test_host_service_start_failure_closes_started_services(tmp_path: Path) -> None:
    app = await (standard_agent(tmp_path)
                 .with_config_environment(_test_config(tmp_path))
                 .with_llm_runner(FakeLLM(())).build().build_runtime())
    first, failing = _RecordingService(), _RecordingService(fail_start=True)
    app.mount_service(first)
    app.mount_service(failing)
    try:
        with pytest.raises(RuntimeError, match="start failed"):
            await app.activate()
        assert not app.is_available
        assert first.stopped == 1 and failing.stopped == 0
    finally:
        await app.close()


@pytest.mark.integration
async def test_host_service_cleanup_collects_failure_and_continues(tmp_path: Path) -> None:
    app = await (standard_agent(tmp_path)
                 .with_config_environment(_test_config(tmp_path))
                 .with_llm_runner(FakeLLM(())).build().build_runtime())
    first, failing = _RecordingService(), _RecordingService(fail_stop=True)
    app.mount_service(first)
    app.mount_service(failing)
    await app.activate()
    diagnostics = await app.close()
    assert first.stopped == failing.stopped == 1
    assert any(item.error_type == "RuntimeError" for item in diagnostics)
