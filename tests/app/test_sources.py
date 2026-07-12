from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from threading import Event

from tinysoul.app import InputEvent, TerminalInputSource


@dataclass
class _RecordingInputSink:
    events: list[InputEvent] = field(default_factory=list)
    eof_received: Event = field(default_factory=Event)

    def submit(self, event: InputEvent) -> None:
        self.events.append(event)
        if event.source == "terminal.eof":
            self.eof_received.set()


def test_terminal_eof_submits_configured_program_exit() -> None:
    sink = _RecordingInputSink()
    source = TerminalInputSource(
        stream=StringIO("hello\n"),
        eof_command="quit-now",
    )

    source.start(sink)

    assert sink.eof_received.wait(timeout=1.0)
    assert [(event.text, event.source) for event in sink.events] == [
        ("hello\n", "terminal"),
        ("quit-now", "terminal.eof"),
    ]
