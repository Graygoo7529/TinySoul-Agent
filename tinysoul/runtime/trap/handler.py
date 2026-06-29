"""Trap handlers and trap results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..transfer import RuntimeTransfer
from ..signals.base import Signal
from .context import TrapSnap


@dataclass(frozen=True)
class TrapResult:
    """Result returned by a trap handler."""

    transfer: RuntimeTransfer
    signals: tuple[Signal, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "signals", tuple(self.signals))
        for signal in self.signals:
            if not isinstance(signal, Signal):
                raise TypeError("TrapResult.signals must contain Signal values")


class TrapHandler(Protocol):
    """Protocol for trap handlers."""

    def handle(self, snap: TrapSnap) -> TrapResult:
        """Handle a trap snapshot and return a transfer."""
        ...
