"""Endpoint Observation replay engine."""

from __future__ import annotations

from typing import Generic

from tinysoul.infra.json import JsonObject
from tinysoul.runtime import ObservationLevel

from ..events import EndpointEventPage
from .contracts import EndpointGenerationT
from .context import EndpointEngineContext


class EndpointEventsEngine(Generic[EndpointGenerationT]):
    """Expose the owned event buffer without leaking it to HTTP routes."""

    def __init__(self, context: EndpointEngineContext[EndpointGenerationT]) -> None:
        self._context = context

    @property
    def latest_sequence(self) -> int:
        return self._context.events.latest_sequence

    def journal_status(self) -> JsonObject:
        return self._context.events.journal_status()

    def replay(
        self,
        *,
        after: int,
        mode: ObservationLevel,
        limit: int,
    ) -> EndpointEventPage:
        return self._context.events.replay(after=after, mode=mode, limit=limit)

    def wait_after(
        self,
        *,
        after: int,
        mode: ObservationLevel,
        timeout_seconds: float,
    ) -> EndpointEventPage:
        return self._context.events.wait_after(
            after=after,
            mode=mode,
            timeout_seconds=timeout_seconds,
        )
