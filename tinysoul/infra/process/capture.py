"""Incremental child output decoding into the sole UTF-8 log."""

import codecs
import ctypes
from enum import StrEnum
import io
import os
from pathlib import Path
from threading import Lock, Thread
from typing import IO

from .errors import ManagedProcessCloseError, ProcessEncodingError, ProcessOutputError


class OutputEncoding(StrEnum):
    PLATFORM = "platform"


def text_encoding(value: str) -> str:
    """Resolve an explicit text codec; platform means Windows OEM or UTF-8."""
    if value == OutputEncoding.PLATFORM:
        value = (
            f"cp{ctypes.windll.kernel32.GetOEMCP()}" if os.name == "nt" else "utf-8"
        )
    try:
        codec = codecs.lookup(value)
        "".encode(codec.name)
        decoder = codecs.getincrementaldecoder(codec.name)(errors="replace")
        if not isinstance(decoder.decode(b"", final=True), str):
            raise ProcessEncodingError("Output encoding must be a text codec")
    except (LookupError, TypeError, ValueError) as exc:
        raise ProcessEncodingError("Unknown or unsupported output text encoding") from exc
    return codec.name


class OutputCapture:
    """One pipe reader; reads never wait for a newline or a full buffer."""

    def __init__(self, source: IO[bytes], path: Path, encoding: str) -> None:
        self._source = source
        self._target = path.open("wb", buffering=0)
        self._decoder = io.IncrementalNewlineDecoder(
            codecs.getincrementaldecoder(encoding)(errors="replace"), translate=True
        )
        self._lock = Lock()
        self._failure: Exception | None = None
        self._thread = Thread(target=self._run, name="process-output", daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            self._target.close()
            raise

    def _run(self) -> None:
        try:
            while True:
                data = os.read(self._source.fileno(), 16384)
                text = self._decoder.decode(data, final=not data)
                if text:
                    with self._lock:
                        self._target.write(text.encode("utf-8"))
                if not data:
                    break
        except Exception as exc:
            self._failure = exc
        finally:
            self._source.close()

    def flush(self) -> None:
        with self._lock:
            if self._failure is not None:
                raise ProcessOutputError(
                    "Process output could not be collected"
                ) from self._failure

    def finish(self, timeout_seconds: float) -> None:
        self._thread.join(timeout_seconds)
        if self._thread.is_alive():
            raise ManagedProcessCloseError("Process output collection did not finish")
        self.flush()

    def close(self) -> None:
        self._target.close()
