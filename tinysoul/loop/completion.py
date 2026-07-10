"""Turn completion records and post-Turn processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from tinysoul.context import TurnSummary

from .signals import TurnOutput


@dataclass(frozen=True)
class TurnCompletion:
    """Stable data passed to post-Turn services such as a future Session module."""

    summary: TurnSummary
    output: TurnOutput | None = None
    exhausted: bool = False


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
