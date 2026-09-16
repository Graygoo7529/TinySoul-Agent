"""Terminal observation rendering owned by the command-line gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
import sys
from threading import RLock
from typing import TextIO

from tinysoul.infra.json import dumps_json
from tinysoul.runtime import ObservationEvent
from .errors import ConsoleOutputError


@dataclass
class ConsoleOutputSink:
    """Plain terminal renderer with stdout reserved for final answers."""

    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)
    max_chars: int = 20000

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_chars, bool)
            or not isinstance(self.max_chars, int)
            or self.max_chars <= 0
        ):
            raise ConsoleOutputError("Console output max_chars must be positive")
        self._lock = RLock()

    def write(self, event: ObservationEvent) -> None:
        with self._lock:
            if event.name == "turn.output":
                text = event.payload.get("text", event.message)
                rendered = text if isinstance(text, str) else event.message
                self.stdout.write(rendered.rstrip() + "\n")
                self.stdout.flush()
                return
            detail = event.message or event.name
            if event.payload:
                detail = f"{detail} | {dumps_json(event.payload)}"
            rendered = f"[{event.name}] {_clip(detail, self.max_chars)}"
            self.stderr.write(rendered.rstrip() + "\n")
            self.stderr.flush()


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."
