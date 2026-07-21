from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from threading import Event, RLock, Thread

import pytest

from tinysoul.app import (
    AppSettings,
    AppCommandGateway,
    InputCommandParser,
    InputDispatcher,
    InputEvent,
    ProjectInitializer,
    SchedulerSettings,
    HomeDecisionBroker,
    TinySoulAppBuilder,
)
from tinysoul.app.maintenance import MaintenanceDecisionRoute
from tinysoul.home import (
    AgentHomeEngineBuilder,
    AgentHomeSettings,
    HomeMaintenanceChange,
    HomeMaintenanceDecision,
)
from tinysoul.home.overlay import HomeOverlayState
from tinysoul.infra.config import ConfigEnvironment
from tinysoul.llm import TaskCall, TaskResult
from tinysoul.loop import ProgramInputEvent, ProgramOutcome, ProgramWorkStatus
from tinysoul.runtime import (
    ObservationEvent,
    ObservationLevel,
    RuntimeInputBlockedError,
    SignalBus,
)


@dataclass
class _RecordingObservations:
    events: list[ObservationEvent] = field(default_factory=list)
    emitted: Event = field(default_factory=Event)

    def enabled(self, level: ObservationLevel) -> bool:
        return True

    def emit(self, event: ObservationEvent) -> None:
        self.events.append(event)
        self.emitted.set()


def test_terminal_home_decision_broker_only_consumes_pending_decision() -> None:
    observations = _RecordingObservations()
    broker = HomeDecisionBroker(observations=observations)
    decisions: list[HomeMaintenanceDecision | None] = []
    thread = Thread(target=lambda: decisions.append(broker.decide(_change())))

    assert broker.route("apply", source="terminal") is MaintenanceDecisionRoute.NOT_CONSUMED
    thread.start()
    assert observations.emitted.wait(timeout=2.0)
    assert broker.pending is True
    assert broker.route("ordinary input", source="terminal") is MaintenanceDecisionRoute.NOT_CONSUMED
    assert broker.route("apply", source="terminal") is MaintenanceDecisionRoute.CONSUMED
    thread.join(timeout=2.0)

    assert thread.is_alive() is False
    assert decisions == [HomeMaintenanceDecision.APPLY]
    prompt = observations.events[0]
    assert prompt.name == "home.maintenance.decision.required"
    assert prompt.level is ObservationLevel.NORMAL
    assert prompt.payload["decision_required"] is True
    resolved = observations.events[1]
    assert resolved.name == "home.maintenance.decision.resolved"
    assert resolved.payload["decision"] == "apply"


def test_terminal_eof_stops_pending_review_and_requests_program_exit() -> None:
    observations = _RecordingObservations()
    broker = HomeDecisionBroker(observations=observations)
    decisions: list[HomeMaintenanceDecision | None] = []
    thread = Thread(target=lambda: decisions.append(broker.decide(_change())))
    thread.start()
    assert observations.emitted.wait(timeout=2.0)

    route = broker.route("", source="terminal.eof")
    thread.join(timeout=2.0)

    assert route is MaintenanceDecisionRoute.CONSUMED_AND_EXIT
    assert decisions == [None]


def test_program_exit_can_stop_pending_manual_review() -> None:
    observations = _RecordingObservations()
    broker = HomeDecisionBroker(observations=observations)
    decisions: list[HomeMaintenanceDecision | None] = []
    thread = Thread(target=lambda: decisions.append(broker.decide(_change())))
    thread.start()
    assert observations.emitted.wait(timeout=2.0)

    assert broker.stop_pending(source="terminal") is True
    thread.join(timeout=2.0)

    assert thread.is_alive() is False
    assert decisions == [None]
    assert broker.stop_pending(source="terminal") is False


def test_gateway_requires_typed_endpoint_decision_while_terminal_can_reply() -> None:
    observations = _RecordingObservations()
    broker = HomeDecisionBroker(observations=observations)
    queue: Queue[ProgramInputEvent] = Queue()
    bus = SignalBus()
    dispatcher = InputDispatcher(
        parser=InputCommandParser(),
        bus=bus,
        program_inputs=queue,
        active_turn_scope=lambda: None,
    )
    gateway = AppCommandGateway(
        dispatcher=dispatcher,
        decisions=broker,
        bus=bus,
        active_turn_scope=lambda: None,
    )
    decisions: list[HomeMaintenanceDecision | None] = []
    thread = Thread(target=lambda: decisions.append(broker.decide(_change())))
    thread.start()
    assert observations.emitted.wait(timeout=2.0)

    try:
        with pytest.raises(RuntimeInputBlockedError):
            gateway.submit_user_input("apply", source="endpoint", metadata={})

        assert broker.pending is True
        assert queue.empty()
        gateway.submit(InputEvent("apply", source="terminal"))
    finally:
        if broker.pending:
            broker.stop_pending(source="test.cleanup")
    thread.join(timeout=2.0)

    assert decisions == [HomeMaintenanceDecision.APPLY]


def test_app_manual_home_maintenance_reviews_and_applies_runtime_diff(
    tmp_path: Path,
) -> None:
    config = _test_config(tmp_path)
    home = AgentHomeEngineBuilder(
        AgentHomeSettings(
            original_root=tmp_path / "home",
            runtime_root=tmp_path / "runtime" / "home",
        )
    ).build()
    home.write_top("home:why@manual", "committed after review")
    sink = _DecisionSink()
    app = (
        TinySoulAppBuilder(root=tmp_path)
        .with_config_environment(config)
        .with_app_settings(
            AppSettings(
                interactive=False,
                scheduler=SchedulerSettings(enabled=False),
            )
        )
        .with_llm_runner(_UnusedLLM())
        .with_output_sink(sink)
        .build()
    )
    outcomes: list[ProgramOutcome] = []
    errors: list[BaseException] = []

    def run_app() -> None:
        try:
            outcomes.append(app.run())
        except BaseException as exc:
            errors.append(exc)

    app.submit_input("/maintenance home", source="terminal")
    thread = Thread(target=run_app)
    thread.start()
    assert sink.decision_prompt.wait(timeout=5.0)
    app.submit_interactive_event(InputEvent("apply", source="terminal"))
    app.submit_interactive_event(InputEvent("exit", source="terminal"))
    thread.join(timeout=5.0)

    assert thread.is_alive() is False
    assert errors == []
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.work_count == 1
    assert outcome.works[0].status is ProgramWorkStatus.COMPLETED
    assert (tmp_path / "home" / "why" / "manual.md").read_text(
        encoding="utf-8"
    ) == "committed after review"
    assert home.maintenance_pending().pending is False


def _change() -> HomeMaintenanceChange:
    return HomeMaintenanceChange(
        link="home:why@changed",
        relative_path="why/changed.md",
        state=HomeOverlayState.CREATED,
        baseline_digest="",
        runtime_digest="runtime-digest",
        runtime_size=7,
        runtime_mtime_ns=1,
        runtime_text="changed",
        runtime_truncated=False,
        actual_exists=False,
        actual_digest="",
        actual_text="",
        actual_truncated=False,
    )


@dataclass
class _DecisionSink:
    events: list[ObservationEvent] = field(default_factory=list)
    decision_prompt: Event = field(default_factory=Event)
    _lock: RLock = field(default_factory=RLock)

    def write(self, event: ObservationEvent) -> None:
        with self._lock:
            self.events.append(event)
        if event.payload.get("decision_required") is True:
            self.decision_prompt.set()


class _UnusedLLM:
    def run(self, call: TaskCall) -> TaskResult:
        raise AssertionError("Manual Home Maintenance must not call the LLM")


def _test_config(tmp_path: Path) -> ConfigEnvironment:
    project_root = tmp_path / ".config-project"
    ProjectInitializer().initialize(project_root)
    agent = tmp_path / "home" / "agent" / "AGENT.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("# Test Agent\n", encoding="utf-8")
    return ConfigEnvironment.from_project_root(
        root=project_root,
        overrides={
            "app.interactive": False,
            "home.root": str(tmp_path / "home"),
            "home.runtime_root": str(tmp_path / "runtime" / "home"),
            "memory.root": str(tmp_path / "memory"),
            "session.root": str(tmp_path / "runtime" / "session"),
            "workspace.root": str(tmp_path / "runtime" / "workspace"),
            "loop.daily.archive_root": str(tmp_path / "archive"),
        },
    )
