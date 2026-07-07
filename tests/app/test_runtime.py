from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from tinysoul.app import AppSettings, InputEvent, InputSink, TinySoulAppBuilder
from tinysoul.llm.requests import TaskCall
from tinysoul.llm.responses import TaskResult
from tinysoul.loop import LoopSettings
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


def test_tinysoul_app_starts_and_stops_input_sources() -> None:
    source = _SubmittingSource((InputEvent("exit", source="unit"),))
    app = (
        TinySoulAppBuilder()
        .with_app_settings(AppSettings(interactive=False))
        .with_loop_settings(LoopSettings(max_cycles_per_turn=1))
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


def test_tinysoul_app_submit_event_uses_dispatcher() -> None:
    app = (
        TinySoulAppBuilder()
        .with_app_settings(AppSettings(interactive=False))
        .with_llm_runner(FakeLLM(()))
        .build()
    )

    app.submit_event(InputEvent("exit", source="unit"))
    outcome = app.run()

    assert outcome.transfer is not None
    assert outcome.transfer.action is RuntimeTransferAction.END
    assert outcome.transfer.target.level is RunLevel.PROGRAM
