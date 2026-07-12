"""Terminal input source."""

from __future__ import annotations

import sys
import threading
from typing import TextIO

from tinysoul.app.errors import AppContractError
from tinysoul.app.inputs import InputEvent, InputSink


class TerminalInputSource:
    """Background stdin input source."""

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        eof_command: str = "exit",
    ) -> None:
        if not isinstance(eof_command, str) or not eof_command.strip():
            raise AppContractError(
                "TerminalInputSource.eof_command must be non-empty"
            )
        self._stream = stream or sys.stdin
        self._eof_command = eof_command.strip()
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
                if self._stop_event.is_set():
                    return
                self._stop_event.set()
                sink.submit(
                    InputEvent(
                        text=self._eof_command,
                        source="terminal.eof",
                    )
                )
                return
            sink.submit(InputEvent(text=line, source="terminal"))
