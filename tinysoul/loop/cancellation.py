"""Cooperative Turn-scoped cancellation token."""

from __future__ import annotations

from threading import Event, Lock

from .signals import LoopControlKind


class TurnCancellation:
    """Cooperative cancel flag owned by one running Turn.

    Boundary consumption of control signals stays the authoritative source
    of Turn control flow. The token only accelerates convergence of work
    that is already in flight when the control request arrives: an LLM
    provider call abandons its wait, and an action batch requests
    cooperative cancellation of its executions. The next cycle boundary
    then consumes the pending control signal as usual.
    """

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._kind: LoopControlKind | None = None

    def request(self, kind: LoopControlKind) -> None:
        """Record the first requested control kind and set the flag."""

        with self._lock:
            if self._kind is None:
                self._kind = kind
        self._event.set()

    def requested(self) -> bool:
        return self._event.is_set()

    @property
    def kind(self) -> LoopControlKind | None:
        with self._lock:
            return self._kind
