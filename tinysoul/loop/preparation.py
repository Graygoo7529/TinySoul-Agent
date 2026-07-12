"""Turn preparation lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.runtime import RunScope, Signal

from .day import BusinessDay
from .errors import LoopContractError


class TurnPreparationHandler(Protocol):
    """Produce context signals before the first Cycle of a Turn."""

    def prepare(self, request: "TurnPreparationRequest") -> tuple[Signal, ...]:
        """Return scoped preparation signals."""
        ...


@dataclass(frozen=True)
class TurnPreparationRequest:
    turn_id: str
    user_input: str
    business_day: BusinessDay
    scope: RunScope

    def __post_init__(self) -> None:
        if not self.turn_id or not self.user_input:
            raise LoopContractError(
                "TurnPreparationRequest requires turn_id and user_input"
            )
        if not isinstance(self.business_day, BusinessDay):
            raise LoopContractError(
                "TurnPreparationRequest.business_day must be a BusinessDay"
            )


@dataclass(frozen=True)
class TurnPreparationPipeline:
    """Run ordered Turn preparation handlers."""

    handlers: tuple[TurnPreparationHandler, ...] = field(default_factory=tuple)

    def prepare(self, request: TurnPreparationRequest) -> tuple[Signal, ...]:
        signals: list[Signal] = []
        for handler in self.handlers:
            signals.extend(handler.prepare(request))
        return tuple(signals)
