from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
import sys

import pytest

from tinysoul.app import (
    AppOutputError,
    ConsoleOutputSink,
    ObservationRouter,
)
from tinysoul.runtime import ObservationEvent, ObservationLevel


@dataclass
class _RecordingSink:
    events: list[ObservationEvent] = field(default_factory=list)

    def write(self, event: ObservationEvent) -> None:
        self.events.append(event)


@dataclass
class _FailingSink:
    calls: int = 0

    def write(self, event: ObservationEvent) -> None:
        self.calls += 1
        raise OSError("closed output")


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        (ObservationLevel.NORMAL, ("normal",)),
        (ObservationLevel.VERBOSE, ("normal", "verbose")),
        (ObservationLevel.MODEL, ("normal", "verbose", "model")),
    ),
)
def test_observation_router_filters_three_output_levels(
    mode: ObservationLevel,
    expected: tuple[str, ...],
) -> None:
    sink = _RecordingSink()
    router = ObservationRouter(mode=mode, sinks=(sink,))

    for level in ObservationLevel:
        router.emit(
            ObservationEvent(
                name=level.value,
                level=level,
                source="test",
            )
        )

    assert tuple(event.name for event in sink.events) == expected


def test_observation_router_isolates_and_reports_sink_failure() -> None:
    failing = _FailingSink()
    healthy = _RecordingSink()
    router = ObservationRouter(
        mode=ObservationLevel.NORMAL,
        sinks=(failing, healthy),
    )
    event = ObservationEvent(
        name="turn.output",
        level=ObservationLevel.NORMAL,
        source="loop.turn",
        payload={"text": "answer"},
    )

    router.emit(event)
    router.emit(event)

    assert failing.calls == 1
    assert healthy.events == [event, event]
    with pytest.raises(AppOutputError, match="closed output"):
        router.raise_if_failed()
    router.raise_if_failed()


def test_console_sink_reserves_stdout_for_turn_output() -> None:
    stdout = StringIO()
    stderr = StringIO()
    sink = ConsoleOutputSink(stdout=stdout, stderr=stderr)

    sink.write(
        ObservationEvent(
            name="turn.output",
            level=ObservationLevel.NORMAL,
            source="loop.turn",
            message="final",
            payload={"text": "final answer"},
        )
    )
    sink.write(
        ObservationEvent(
            name="llm.model.started",
            level=ObservationLevel.VERBOSE,
            source="llm.task",
            message="started",
            payload={"model_id": "model_a"},
        )
    )

    assert stdout.getvalue() == "final answer\n"
    assert "llm.model.started" in stderr.getvalue()
    assert "model_a" in stderr.getvalue()


def test_console_sink_resolves_default_streams_when_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    sink = ConsoleOutputSink()

    sink.write(
        ObservationEvent(
            name="turn.output",
            level=ObservationLevel.NORMAL,
            source="loop.turn",
            payload={"text": "current stream"},
        )
    )

    assert stdout.getvalue() == "current stream\n"
