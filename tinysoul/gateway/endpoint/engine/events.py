"""Endpoint Observation replay engine."""

from __future__ import annotations
from dataclasses import replace


from tinysoul.infra.json import JsonObject
from tinysoul.runtime import ObservationLevel

from ..events import EndpointEventPage
from .context import EndpointEngineContext


class EndpointEventsEngine:
    """Expose the owned event buffer without leaking it to HTTP routes."""

    def __init__(self, context: EndpointEngineContext) -> None:
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
        instance_id: str | None = None,
    ) -> EndpointEventPage:
        reset = instance_id is not None and instance_id != self._context.settings.instance_id
        page = self._context.events.replay(after=0 if reset else after, mode=mode, limit=limit)
        return replace(page, gap=True) if reset else page

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
