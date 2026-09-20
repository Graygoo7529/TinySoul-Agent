"""Turn preparation lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.infra.time import CalendarDay
from tinysoul.runtime import RunScope, Signal

from ..errors import LoopContractError


class TurnPreparationHandler(Protocol):
    """Produce context signals before the first Cycle of a Turn."""

    async def prepare(self, request: "TurnPreparationRequest") -> tuple[Signal, ...]:
        """Return scoped preparation signals."""
        ...


@dataclass(frozen=True)
class TurnPreparationRequest:
    turn_id: str
    turn_input: str
    active_day: CalendarDay
    scope: RunScope

    def __post_init__(self) -> None:
        if not self.turn_id or not self.turn_input:
            raise LoopContractError(
                "TurnPreparationRequest requires turn_id and turn_input"
            )
        if not isinstance(self.active_day, CalendarDay):
            raise LoopContractError(
                "TurnPreparationRequest.active_day must be a CalendarDay"
            )


@dataclass(frozen=True)
class TurnPreparationPipeline:
    """Run ordered Turn preparation handlers."""

    handlers: tuple[TurnPreparationHandler, ...] = field(default_factory=tuple)

    async def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        signals: list[Signal] = []
        for handler in self.handlers:
            signals.extend(await handler.prepare(request))
        return tuple(signals)
