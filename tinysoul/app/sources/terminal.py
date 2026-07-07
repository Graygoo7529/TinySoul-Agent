"""Terminal input source."""

from __future__ import annotations

import sys
import threading
from typing import TextIO

from tinysoul.app.inputs import InputEvent, InputSink


class TerminalInputSource:
    """Background stdin input source."""

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
    ) -> None:
        self._stream = stream or sys.stdin
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, sink: InputSink) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(sink,),
            name="tinysoul-terminal-input",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self, sink: InputSink) -> None:
        while not self._stop_event.is_set():
            line = self._stream.readline()
            if line == "":
                self._stop_event.set()
                return
            sink.submit(InputEvent(text=line, source="terminal"))
