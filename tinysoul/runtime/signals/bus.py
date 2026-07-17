"""Thread-safe runtime signal bus."""

from __future__ import annotations

import threading

from ..errors import RuntimeContractError
from .base import Signal


class SignalBus:
    """A thread-safe queue for runtime signals."""

    def __init__(self) -> None:
        self._signals: list[Signal] = []
        self._condition = threading.Condition()
        self._generation = 0

    def emit(self, signal: Signal) -> None:
        if not isinstance(signal, Signal):
            raise RuntimeContractError("SignalBus.emit expects a Signal")
        with self._condition:
            self._signals.append(signal)
            self._generation += 1
            self._condition.notify_all()

    def peek(self) -> tuple[Signal, ...]:
        with self._condition:
            return tuple(self._signals)

    def consume(self) -> tuple[Signal, ...]:
        with self._condition:
            consumed = tuple(self._signals)
            self._signals.clear()
            return consumed

    def consume_namespace(self, prefix: str) -> tuple[Signal, ...]:
        """Consume only signals matching a namespace prefix, keeping the rest queued."""

        if not prefix:
            raise RuntimeContractError(
                "SignalBus.consume_namespace requires a non-empty prefix"
            )
        with self._condition:
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
        with self._condition:
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
        with self._condition:
            return len(self._signals)

    def generation(self) -> int:
        """Return a monotonic snapshot used only for non-consuming wakeups."""

        with self._condition:
            return self._generation

    def wait_for_change(self, generation: int, timeout: float | None) -> int:
        """Wait until a signal is emitted, without consuming business signals."""

        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise RuntimeContractError("Signal generation must be non-negative")
        if timeout is not None and timeout < 0:
            raise RuntimeContractError("Signal wait timeout must be non-negative")
        with self._condition:
            if self._generation == generation:
                self._condition.wait(timeout)
            return self._generation
