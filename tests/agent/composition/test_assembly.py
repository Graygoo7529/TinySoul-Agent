from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from tinysoul.agent.errors import AgentInvariantError
from tinysoul.agent.config import AgentSettings
from tinysoul.environment.inputs import InputEvent
from tinysoul.environment.inputs import InputSink
from tinysoul.agent.composition.builder import AgentBuilder, standard_agent
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.llm.protocol.requests import TaskCall
from tinysoul.llm.protocol.responses import TaskResult
from tinysoul.kernel.loop import LoopSettings, TurnSettings
from tinysoul.plugins.reflection import ReflectionAvailability
from tinysoul.runtime import RuntimeTransferAction, RunLevel
from tests.support.project import copy_initialized_project


class FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    async def run(self, call: TaskCall) -> TaskResult:
        self.calls.append(call)
        return self.results.popleft()


@dataclass
class _SubmittingSource:
    events: tuple[InputEvent, ...]
    started: int = 0
    stopped: int = 0
    submitted: list[InputEvent] = field(default_factory=list)

    def start(self, sink: InputSink) -> None:
        self.started += 1
        for event in self.events:
            sink.submit(event)
            self.submitted.append(event)

    def stop(self) -> None:
        self.stopped += 1


@dataclass
class _FailingStartSource:
    started: int = 0

    def start(self, sink: InputSink) -> None:
        self.started += 1
        raise RuntimeError("start failed")

    def stop(self) -> None:
        raise AssertionError("failed start source should not be stopped")


@dataclass
class _FailingStopSource(_SubmittingSource):
    def stop(self) -> None:
        self.stopped += 1
        raise RuntimeError("stop failed")


@dataclass
class _RecordingService:
    started: int = 0
    stopped: int = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


@dataclass
class _AvailabilityAwareService(_RecordingService):
    availability: Callable[[], ReflectionAvailability] | None = None
    availability_existed_at_start: bool = False

    async def start(self) -> None:
        await super().start()
        assert self.availability is not None
        self.availability_existed_at_start = isinstance(
            self.availability(), ReflectionAvailability
        )


async def test_tinysoul_agent_starts_and_stops_input_sources(tmp_path: Path) -> None:
    source = _SubmittingSource((InputEvent("exit", source="unit"),))
    app = (
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=1)))
        .with_llm_runner(FakeLLM(()))
        .with_input_source(source)
        .build().build_runtime()
    )

    outcome = await app.run()

    assert source.started == 1
    assert source.stopped == 1
    assert [event.text for event in source.submitted] == ["exit"]
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.AGENT


async def test_tinysoul_agent_starts_services_before_inputs_and_stops_them(
    tmp_path: Path,
) -> None:
    service = _RecordingService()
    source = _SubmittingSource((InputEvent("exit", source="unit"),))
    built = (
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_input_source(source)
        .build().build_runtime()
    )
    app = replace(built, services=(service,))

    await app.run()

    assert service.started == 1
    assert source.started == 1
    assert source.stopped == 1
    assert service.stopped == 1


async def test_tinysoul_agent_prepares_availability_before_starting_services(
    tmp_path: Path,
) -> None:
    service = _AvailabilityAwareService()
    source = _SubmittingSource((InputEvent("exit", source="unit"),))
    built = (
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_input_source(source)
        .build().build_runtime()
    )
    service.availability = (
        built.generation_handle.snapshot().generation.reflection.availability
    )
    app = replace(built, services=(service,))

    await app.run()

    assert service.availability_existed_at_start is True


async def test_tinysoul_agent_stops_started_sources_when_later_start_fails(
    tmp_path: Path,
) -> None:
    first = _SubmittingSource(())
    failing = _FailingStartSource()
    app = (
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_input_source(first)
        .with_input_source(failing)
        .build().build_runtime()
    )

    with pytest.raises(RuntimeError, match="start failed"):
        await app.run()

    assert first.started == 1
    assert first.stopped == 1
    assert failing.started == 1


async def test_tinysoul_agent_attempts_all_source_stops_and_reports_failure(
    tmp_path: Path,
) -> None:
    failing = _FailingStopSource((InputEvent("exit", source="unit"),))
    second = _SubmittingSource(())
    app = (
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_input_source(failing)
        .with_input_source(second)
        .build().build_runtime()
    )

    await app.run()
    diagnostics = await app.close()
    assert len(diagnostics) == 1 and diagnostics[0].error_type == "RuntimeError"

    assert failing.stopped == 1
    assert second.stopped == 1


async def test_tinysoul_agent_submit_event_uses_dispatcher(tmp_path: Path) -> None:
    app = (
        await standard_agent(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_agent_settings(AgentSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build().build_runtime()
    )

    await app.submit_event(InputEvent("exit", source="unit"))
    outcome = await app.run()

    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.AGENT


def _test_config(tmp_path: Path) -> ConfigEnvironment:
    project_root = tmp_path / ".config-project"
    copy_initialized_project(project_root)
    home_root = tmp_path / "home"
    agent_path = home_root / "agent" / "AGENT.md"
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path.write_text("# Test Agent\n", encoding="utf-8")
    return ConfigEnvironment.from_project_root(
        root=project_root,
        overrides={
            "agent.interactive": False,
            "home.root": str(home_root),
            "home.runtime_root": str(tmp_path / "runtime" / "home"),
            "memory.root": str(tmp_path / "memory"),
            "session.root": str(tmp_path / "runtime" / "session"),
            "workspace.root": str(tmp_path / "runtime" / "workspace"),
            "reflection.archive_root": str(tmp_path / "archive"),
        },
    )
