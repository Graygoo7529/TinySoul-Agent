"""Thread-safe runtime signal bus."""

from __future__ import annotations

import threading

from .base import Signal


class SignalBus:
    """A thread-safe queue for runtime signals."""

    def __init__(self) -> None:
        self._signals: list[Signal] = []
        self._lock = threading.Lock()

    def emit(self, signal: Signal) -> None:
        if not isinstance(signal, Signal):
            raise TypeError("SignalBus.emit expects a Signal")
        with self._lock:
            self._signals.append(signal)

    def peek(self) -> tuple[Signal, ...]:
        with self._lock:
            return tuple(self._signals)

    def consume(self) -> tuple[Signal, ...]:
        with self._lock:
            consumed = tuple(self._signals)
            self._signals.clear()
            return consumed

    def __len__(self) -> int:
        with self._lock:
            return len(self._signals)
