from __future__ import annotations

from io import StringIO
import sys
from typing import cast

import pytest

from tinysoul.agent.observation.outputs import ObservationRoute, ObservationRouter
from tinysoul.gateway.console import ConsoleMode, ConsoleMonitor
from tinysoul.runtime import ObservationEvent, ObservationLevel


def event(name: str, **payload) -> ObservationEvent:
    return ObservationEvent(name=name, source="test", level=ObservationLevel.VERBOSE, payload=payload)


@pytest.mark.parametrize("mode", ConsoleMode)
def test_monitor_selects_summaries_without_rendering_content(mode: ConsoleMode) -> None:
    output = StringIO()
    monitor = ConsoleMonitor(mode, output)
    monitor.report("backend ready")
    monitor.write(event("turn.started", request_id="request-1"))
    monitor.write(event("turn.failed", kind="llm.provider", message="private exception"))
    for name in ("turn.output", "llm.request", "action.result"):
        monitor.write(event(name, action="probe", status="completed", text="private body", payload={"raw": "secret"}))
    rendered = output.getvalue()
    assert "backend ready" in rendered
    assert "llm.provider" in rendered
    assert ("request-1" in rendered) is (mode is ConsoleMode.DETAIL)
    assert "private" not in rendered and "secret" not in rendered
    assert all(len(line) < 700 for line in rendered.splitlines())


@pytest.mark.parametrize("mode", ConsoleMode)
def test_console_does_not_change_endpoint_model_events(mode: ConsoleMode) -> None:
    events = []

    class Sink:
        def write(self, event):
            events.append(event)

    monitor = ConsoleMonitor(mode, StringIO())
    router = ObservationRouter(routes=(
        ObservationRoute(monitor, ObservationLevel.VERBOSE),
        ObservationRoute(Sink(), ObservationLevel.MODEL),
    ))
    model = ObservationEvent(name="llm.request", source="test", level=ObservationLevel.MODEL, payload={"messages": ["content"]})
    router.emit(model)
    assert events == [model]
    assert cast(StringIO, monitor.stream).getvalue() == ""


def test_monitor_resolves_stderr_and_contains_stream_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    monitor = ConsoleMonitor()
    monitor.report("ready")
    assert stream.getvalue()
    stream.close()
    monitor.report("stopping")
    monitor.report("stopped")
    assert monitor.failure is not None
    assert monitor.failure.resource == "console"
