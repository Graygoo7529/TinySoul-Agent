"""Declared event subscriptions projected into the existing Context batch."""

from collections.abc import Callable
from dataclasses import dataclass

from tinysoul.runtime import RunScope, Signal
from tinysoul.runtime.events import EnvironmentEvent, EventFilter
from ..errors import LoopInvariantError


@dataclass(frozen=True)
class TurnEventSubscription:
    filter: EventFilter
    adapt: Callable[[EnvironmentEvent, RunScope], tuple[Signal, ...]]
    coalesce: bool = False
    requires_decision: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.filter, EventFilter) or not callable(self.adapt):
            raise LoopInvariantError("Event subscriptions require a filter and adapter")
        if self.coalesce and (self.filter.topic is None or self.filter.source is None):
            raise LoopInvariantError("State coalescing requires a bounded topic/source identity")
