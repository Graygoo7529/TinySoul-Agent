"""Thread-safe runtime signal bus."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
import threading
from time import monotonic

from ..errors import RuntimeContractError
from .base import Signal


class SignalBus:
    """A thread-safe queue for runtime signals."""

    def __init__(self) -> None:
        self._signals: list[Signal] = []
        self._condition = threading.Condition()
        self._generation = 0
        self._emissions: deque[tuple[int, Signal]] = deque()
        self._watchers: dict[int, int] = {}
        self._next_watcher_id = 1

    def emit(self, signal: Signal) -> None:
        if not isinstance(signal, Signal):
            raise RuntimeContractError("SignalBus.emit expects a Signal")
        with self._condition:
            self._generation += 1
            self._signals.append(signal)
            if self._watchers:
                self._emissions.append((self._generation, signal))
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

    def watch(self) -> "SignalWatch":
        """Open one non-consuming emission cursor at the current generation."""

        with self._condition:
            watcher_id = self._next_watcher_id
            self._next_watcher_id += 1
            self._watchers[watcher_id] = self._generation
            return SignalWatch(self, watcher_id)

    def _wait_for_matching(
        self,
        watcher_id: int,
        predicate: Callable[[Signal], bool],
        timeout: float | None,
    ) -> Signal | None:
        """Advance one registered watcher to a later matching emission."""

        if not callable(predicate):
            raise RuntimeContractError("Signal predicate must be callable")
        if timeout is not None and timeout < 0:
            raise RuntimeContractError("Signal wait timeout must be non-negative")
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            while True:
                cursor = self._watchers.get(watcher_id)
                if cursor is None:
                    raise RuntimeContractError("Signal watcher is closed")
                effective_cursor = cursor
                for sequence, signal in self._emissions:
                    if sequence <= effective_cursor:
                        continue
                    effective_cursor = sequence
                    if predicate(signal):
                        self._watchers[watcher_id] = effective_cursor
                        self._prune_emissions()
                        return signal
                effective_cursor = max(effective_cursor, self._generation)
                self._watchers[watcher_id] = effective_cursor
                self._prune_emissions()
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def _close_watcher(self, watcher_id: int) -> None:
        with self._condition:
            self._watchers.pop(watcher_id, None)
            self._prune_emissions()

    def _prune_emissions(self) -> None:
        if not self._watchers:
            self._emissions.clear()
            return
        floor = min(self._watchers.values())
        while self._emissions and self._emissions[0][0] <= floor:
            self._emissions.popleft()


class SignalWatch:
    """One closeable, non-consuming view over future Signal emissions."""

    def __init__(self, bus: SignalBus, watcher_id: int) -> None:
        self._bus = bus
        self._watcher_id = watcher_id
        self._closed = False

    def wait_for_matching(
        self,
        predicate: Callable[[Signal], bool],
        timeout: float | None,
    ) -> Signal | None:
        if self._closed:
            raise RuntimeContractError("Signal watcher is closed")
        return self._bus._wait_for_matching(self._watcher_id, predicate, timeout)

    def close(self) -> None:
        if self._closed:
            return
        self._bus._close_watcher(self._watcher_id)
        self._closed = True

    def __enter__(self) -> "SignalWatch":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
