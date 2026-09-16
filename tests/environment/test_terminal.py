from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from threading import Event
import os

from tinysoul.environment.inputs import CommandReceipt
from tinysoul.environment.inputs import InputEvent
from tinysoul.environment.terminal import TerminalInputSource


@dataclass
class _RecordingInputSink:
    events: list[InputEvent] = field(default_factory=list)
    eof_received: Event = field(default_factory=Event)

    def submit(self, event: InputEvent) -> CommandReceipt:
        self.events.append(event)
        if event.source == "terminal.eof":
            self.eof_received.set()
        return CommandReceipt(True, event.command_id, "test", "accepted")


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
    source.stop()
    assert not source.running


def test_terminal_stop_joins_idle_pipe_reader_and_restores_borrowed_mode() -> None:
    descriptor, writer = os.pipe()
    with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
        try:
            sink = _RecordingInputSink()
            source = TerminalInputSource(stream=stream)
            for _ in range(3):
                source.start(sink)
                source.stop()
                assert not source.running
                assert os.get_blocking(descriptor)
            assert not sink.events and not stream.closed
        finally:
            os.close(writer)


def test_terminal_pipe_decodes_split_unicode_and_flushes_final_line() -> None:
    descriptor, writer = os.pipe()
    with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
        sink = _RecordingInputSink()
        source = TerminalInputSource(stream=stream)
        try:
            source.start(sink)
            encoded = "你好\r\nlast".encode("utf-8")
            os.write(writer, encoded[:1])
            os.write(writer, encoded[1:])
        finally:
            os.close(writer)
        assert sink.eof_received.wait(timeout=2)
        source.stop()
        assert [item.text for item in sink.events] == ["你好\n", "last", "exit"]
