from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from tinysoul.app import (
    AppInvariantError,
    AppSettings,
    InputEvent,
    InputSink,
    ProjectInitializer,
    TinySoulAppBuilder,
)
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import TaskResult
from tinysoul.loop import LoopSettings, TurnSettings
from tinysoul.runtime import RuntimeTransferAction, RunLevel


class FakeLLM:
    def __init__(self, results: tuple[TaskResult, ...]) -> None:
        self.results = deque(results)
        self.calls: list[TaskCall] = []

    def run(self, call: TaskCall) -> TaskResult:
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

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


@dataclass
class _AvailabilityAwareService(_RecordingService):
    availability_path: Path = Path()
    availability_existed_at_start: bool = False

    def start(self) -> None:
        super().start()
        self.availability_existed_at_start = self.availability_path.is_file()


def test_tinysoul_app_starts_and_stops_input_sources(tmp_path: Path) -> None:
    source = _SubmittingSource((InputEvent("exit", source="unit"),))
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_loop_settings(LoopSettings(user=TurnSettings(max_cycles=1)))
        .with_llm_runner(FakeLLM(()))
        .with_input_source(source)
        .build()
    )

    outcome = app.run()

    assert source.started == 1
    assert source.stopped == 1
    assert [event.text for event in source.submitted] == ["exit"]
    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.PROGRAM


def test_tinysoul_app_starts_services_before_inputs_and_stops_them(
    tmp_path: Path,
) -> None:
    service = _RecordingService()
    source = _SubmittingSource((InputEvent("exit", source="unit"),))
    built = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_input_source(source)
        .build()
    )
    app = replace(built, services=(service,))

    app.run()

    assert service.started == 1
    assert source.started == 1
    assert source.stopped == 1
    assert service.stopped == 1


def test_tinysoul_app_prepares_availability_before_starting_services(
    tmp_path: Path,
) -> None:
    service = _AvailabilityAwareService(
        availability_path=tmp_path / "runtime" / "maintenance" / "availability.json"
    )
    source = _SubmittingSource((InputEvent("exit", source="unit"),))
    built = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_input_source(source)
        .build()
    )
    app = replace(built, services=(service,))

    app.run()

    assert service.availability_existed_at_start is True


def test_tinysoul_app_stops_started_sources_when_later_start_fails(
    tmp_path: Path,
) -> None:
    first = _SubmittingSource(())
    failing = _FailingStartSource()
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_input_source(first)
        .with_input_source(failing)
        .build()
    )

    with pytest.raises(RuntimeError, match="start failed"):
        app.run()

    assert first.started == 1
    assert first.stopped == 1
    assert failing.started == 1


def test_tinysoul_app_attempts_all_source_stops_and_reports_failure(
    tmp_path: Path,
) -> None:
    failing = _FailingStopSource((InputEvent("exit", source="unit"),))
    second = _SubmittingSource(())
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .with_input_source(failing)
        .with_input_source(second)
        .build()
    )

    with pytest.raises(AppInvariantError, match="Failed to stop app sources"):
        app.run()

    assert failing.stopped == 1
    assert second.stopped == 1


def test_tinysoul_app_submit_event_uses_dispatcher(tmp_path: Path) -> None:
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(_test_config(tmp_path))
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )

    app.submit_event(InputEvent("exit", source="unit"))
    outcome = app.run()

    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.PROGRAM


def _test_config(tmp_path: Path) -> ConfigEnvironment:
    project_root = tmp_path / ".config-project"
    ProjectInitializer().initialize(project_root)
    home_root = tmp_path / "home"
    agent_path = home_root / "agent" / "AGENT.md"
    agent_path.parent.mkdir(parents=True, exist_ok=True)
    agent_path.write_text("# Test Agent\n", encoding="utf-8")
    return ConfigEnvironment.from_project_root(
        root=project_root,
        overrides={
            "app.interactive": False,
            "home.root": str(home_root),
            "home.runtime_root": str(tmp_path / "runtime" / "home"),
            "memory.root": str(tmp_path / "memory"),
            "session.root": str(tmp_path / "runtime" / "session"),
            "workspace.root": str(tmp_path / "runtime" / "workspace"),
            "maintenance.archive_root": str(tmp_path / "archive"),
            "maintenance.runtime_root": str(
                tmp_path / "runtime" / "maintenance"
            ),
        },
    )
