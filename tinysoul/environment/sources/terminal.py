"""Terminal input source."""

from __future__ import annotations

import codecs
from collections.abc import Iterator
from io import StringIO
import os
import stat
import sys
import threading
from typing import TextIO

from ..errors import EnvironmentError
from ..inputs import InputEvent, InputSink


class TerminalInputSource:
    """One stoppable reader for borrowed console, pipe, file or memory input."""

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        eof_command: str = "exit",
    ) -> None:
        if not isinstance(eof_command, str) or not eof_command.strip():
            raise EnvironmentError("TerminalInputSource.eof_command must be non-empty")
        self._stream = stream or sys.stdin
        self._eof_command = eof_command.strip()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, sink: InputSink) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run,
            args=(sink,),
            name="tinysoul-terminal-input",
            daemon=False,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
            if thread.is_alive():
                raise EnvironmentError("Terminal input did not stop")
        self._thread = None
        if self._error is not None:
            raise EnvironmentError("Terminal input failed") from self._error

    def _run(self, sink: InputSink) -> None:
        pending = ""
        try:
            for chunk in self._chunks():
                if self._stop_event.is_set():
                    return
                pending += chunk
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    sink.submit(
                        InputEvent(text=line.rstrip("\r") + "\n", source="terminal")
                    )
                if len(pending) > 64_000:
                    raise EnvironmentError(
                        "Terminal input line exceeds its bounded buffer"
                    )
            if not self._stop_event.is_set():
                if pending:
                    sink.submit(InputEvent(text=pending, source="terminal"))
                sink.submit(InputEvent(text=self._eof_command, source="terminal.eof"))
        except Exception as exc:
            self._error = exc
        finally:
            self._stop_event.set()

    def _chunks(self) -> Iterator[str]:
        if isinstance(self._stream, StringIO):
            while not self._stop_event.is_set():
                chunk = self._stream.read(4096)
                if not chunk:
                    return
                yield chunk
            return
        try:
            descriptor = self._stream.fileno()
        except (OSError, ValueError) as exc:
            raise EnvironmentError("Terminal input requires a pollable stream") from exc
        if os.name == "nt" and self._stream.isatty():
            yield from self._console_chunks()
            return
        mode = os.fstat(descriptor).st_mode
        nonblocking = not stat.S_ISREG(mode)
        original_blocking = os.get_blocking(descriptor) if nonblocking else True
        if nonblocking:
            os.set_blocking(descriptor, False)
        decoder = codecs.getincrementaldecoder(self._stream.encoding or "utf-8")(
            errors="replace"
        )
        try:
            while not self._stop_event.is_set():
                try:
                    data = os.read(descriptor, 4096)
                except BlockingIOError:
                    self._stop_event.wait(0.025)
                    continue
                if not data:
                    remainder = decoder.decode(b"", final=True)
                    if remainder:
                        yield remainder
                    return
                text = decoder.decode(data)
                if text:
                    yield text
        finally:
            if nonblocking:
                os.set_blocking(descriptor, original_blocking)

    def _console_chunks(self) -> Iterator[str]:
        if sys.platform != "win32":
            raise EnvironmentError("Windows console input requires Windows")
        import msvcrt

        pending = ""
        extended = False
        while not self._stop_event.is_set():
            if not msvcrt.kbhit():
                self._stop_event.wait(0.025)
                continue
            char = msvcrt.getwch()
            if extended:
                extended = False
                continue
            if char in {"\x00", "\xe0"}:
                extended = True
            elif char == "\x1a":
                if pending:
                    yield pending
                return
            elif char in {"\r", "\n"}:
                msvcrt.putwch("\r")
                msvcrt.putwch("\n")
                yield pending + "\n"
                pending = ""
            elif char == "\b":
                if pending:
                    pending = pending[:-1]
                    for item in "\b \b":
                        msvcrt.putwch(item)
            elif char >= " ":
                if len(pending) >= 64_000:
                    raise EnvironmentError(
                        "Terminal input line exceeds its bounded buffer"
                    )
                pending += char
                msvcrt.putwch(char)
