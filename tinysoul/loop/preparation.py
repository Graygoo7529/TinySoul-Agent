"""Turn preparation lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.runtime import RunScope, Signal


class TurnPreparationHandler(Protocol):
    """Produce context signals before the first Cycle of a Turn."""

    def prepare(self, *, turn_id: str, scope: RunScope) -> tuple[Signal, ...]:
        """Return scoped preparation signals."""
        ...


@dataclass(frozen=True)
class TurnPreparationPipeline:
    """Run ordered Turn preparation handlers."""

    handlers: tuple[TurnPreparationHandler, ...] = field(default_factory=tuple)

    def prepare(self, *, turn_id: str, scope: RunScope) -> tuple[Signal, ...]:
        signals: list[Signal] = []
        for handler in self.handlers:
            signals.extend(handler.prepare(turn_id=turn_id, scope=scope))
        return tuple(signals)
