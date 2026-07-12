"""Turn completion records and post-Turn processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.context import TurnSummary

from .day import BusinessDay
from .errors import LoopContractError
from .signals import TurnOutput


@dataclass(frozen=True)
class TurnCompletion:
    """Stable data passed to ordered post-Turn services such as Session."""

    summary: TurnSummary
    business_day: BusinessDay
    output: TurnOutput | None = None
    exhausted: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.business_day, BusinessDay):
            raise LoopContractError(
                "TurnCompletion.business_day must be a BusinessDay"
            )
        if not isinstance(self.exhausted, bool):
            raise LoopContractError("TurnCompletion.exhausted must be a boolean")


class TurnCompletionHandler(Protocol):
    """One ordered post-Turn side effect."""

    def handle(self, completion: TurnCompletion) -> None:
        """Process a completed Turn or raise a mapped RuntimeException."""
        ...


@dataclass(frozen=True)
class TurnCompletionPipeline:
    """Run post-Turn handlers in deterministic registration order."""

    handlers: tuple[TurnCompletionHandler, ...] = field(default_factory=tuple)

    def run(self, completion: TurnCompletion) -> None:
        for handler in self.handlers:
            handler.handle(completion)
