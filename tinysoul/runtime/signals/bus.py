"""Thread-safe runtime signal bus."""

from __future__ import annotations

import threading

from ..errors import RuntimeContractError
from .base import Signal


class SignalBus:
    """A thread-safe queue for runtime signals."""

    def __init__(self) -> None:
        self._signals: list[Signal] = []
        self._lock = threading.Lock()

    def emit(self, signal: Signal) -> None:
        if not isinstance(signal, Signal):
            raise RuntimeContractError("SignalBus.emit expects a Signal")
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

    def consume_namespace(self, prefix: str) -> tuple[Signal, ...]:
        """Consume only signals matching a namespace prefix, keeping the rest queued."""

        if not prefix:
            raise RuntimeContractError(
                "SignalBus.consume_namespace requires a non-empty prefix"
            )
        with self._lock:
            matched: list[Signal] = []
            remaining: list[Signal] = []
            for signal in self._signals:
                if signal.name == prefix or signal.name.startswith(f"{prefix}."):
                    matched.append(signal)
                else:
                    remaining.append(signal)
            self._signals = remaining
            return tuple(matched)

    def consume_name(self, name: str) -> tuple[Signal, ...]:
        """Consume only signals matching one exact signal name."""

        if not name:
            raise RuntimeContractError(
                "SignalBus.consume_name requires a non-empty name"
            )
        with self._lock:
            matched: list[Signal] = []
            remaining: list[Signal] = []
            for signal in self._signals:
                if signal.name == name:
                    matched.append(signal)
                else:
                    remaining.append(signal)
            self._signals = remaining
            return tuple(matched)

    def __len__(self) -> int:
        with self._lock:
            return len(self._signals)
