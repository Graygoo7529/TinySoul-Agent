"""Bounded replayable Endpoint observation stream."""

from __future__ import annotations

from collections import deque
from threading import Condition
from time import monotonic

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.runtime import ObservationEvent, ObservationLevel

from ..errors import EndpointContractError, EndpointInvariantError
from .journal import EndpointEventJournal
from .models import EndpointEventEnvelope, EndpointEventPage, EventFilter


class EndpointEventBuffer:
    """Output sink retaining a bounded, ordered event replay window."""

    def __init__(
        self,
        *,
        capacity: int,
        max_bytes: int,
        page_bytes: int = 1024 * 1024,
        journal: EndpointEventJournal | None = None,
    ) -> None:
        if capacity <= 0 or max_bytes <= 0 or page_bytes <= 0:
            raise EndpointContractError("Endpoint event bounds must be positive")
        self._capacity = capacity
        self._max_bytes = max_bytes
        self._page_bytes = page_bytes
        self._journal = journal
        self._events: deque[EndpointEventEnvelope] = deque()
        self._bytes = 0
        self._sequence = journal.latest_sequence if journal is not None else 0
        self._condition = Condition()

    @property
    def latest_sequence(self) -> int:
        with self._condition:
            return self._sequence

    @property
    def journal(self) -> EndpointEventJournal | None:
        return self._journal

    def journal_status(self) -> JsonObject:
        journal = self._journal
        if journal is None:
            return {
                "enabled": False,
                "degraded": False,
                "oldest_sequence": None,
                "latest_sequence": 0,
            }
        return {
            "enabled": True,
            "degraded": journal.degraded,
            "oldest_sequence": journal.oldest_sequence,
            "latest_sequence": journal.latest_sequence,
            **({"failure": journal.failure} if journal.failure is not None else {}),
        }

    def write(self, event: ObservationEvent) -> None:
        with self._condition:
            sequence = self._sequence + 1
            scope: tuple[JsonObject, ...] = tuple(
                {"level": frame.level.value, "name": frame.name}
                for frame in event.scope
            )
            record = to_json_object(
                {
                    "sequence": sequence,
                    "name": event.name,
                    "level": event.level.value,
                    "source": event.source,
                    "scope": list(scope),
                    "message": event.message,
                    "payload": event.payload,
                    "created_at": event.created_at,
                }
            )
            size = len(dumps_json(record).encode("utf-8"))
            if size > self._max_bytes:
                raise EndpointInvariantError(
                    "One observation exceeds the Endpoint event byte budget"
                )
            envelope = EndpointEventEnvelope(
                sequence=sequence,
                name=event.name,
                level=event.level,
                source=event.source,
                scope=scope,
                message=event.message,
                payload=to_json_object(event.payload),
                created_at=event.created_at,
                size_bytes=size,
            )
            self._events.append(envelope)
            self._bytes += size
            self._sequence = sequence
            while len(self._events) > self._capacity or self._bytes > self._max_bytes:
                removed = self._events.popleft()
                self._bytes -= removed.size_bytes
            self._condition.notify_all()
        if self._journal is not None:
            self._journal.append(envelope)

    def replay(
        self,
        *,
        after: int,
        mode: ObservationLevel,
        limit: int = 200,
        filters: EventFilter = EventFilter(),
    ) -> EndpointEventPage:
        if after < 0 or limit <= 0:
            raise EndpointContractError("Endpoint replay bounds are invalid")
        with self._condition:
            memory, sequence, journal = (
                tuple(self._events),
                self._sequence,
                self._journal,
            )
        upper = (
            min(sequence, filters.through) if filters.through is not None else sequence
        )
        memory_oldest = memory[0].sequence if memory else sequence + 1
        oldest = journal.oldest_sequence if journal and not journal.degraded else None
        retained_oldest = oldest if oldest is not None else memory_oldest
        gap = after < retained_oldest - 1 or after > sequence
        if after > sequence:
            after = 0
        selected: list[EndpointEventEnvelope] = []
        scanned, used = after, 0

        def accept(event: EndpointEventEnvelope) -> bool:
            nonlocal scanned, used
            if event.sequence > upper:
                return False
            if _level_rank(event.level) > _level_rank(mode) or not filters.matches(
                event
            ):
                scanned = event.sequence
                return True
            if selected and used + event.size_bytes > self._page_bytes:
                return False
            selected.append(event)
            used += event.size_bytes
            scanned = event.sequence
            return len(selected) < limit

        if journal and not journal.degraded and after < memory_oldest - 1:
            page = journal.read_after_page(
                after=after,
                mode=mode,
                limit=limit,
                filters=filters,
                through=min(upper, memory_oldest - 1),
            )
            for event in page.events:
                if not accept(event):
                    return EndpointEventPage(tuple(selected), scanned, gap)
            scanned = max(scanned, page.scanned_through)
            if not page.complete and not journal.degraded:
                return EndpointEventPage(tuple(selected), scanned, gap)
            gap = gap or journal.degraded
        for event in memory:
            if event.sequence <= scanned or event.sequence > upper:
                continue
            if not accept(event):
                return EndpointEventPage(tuple(selected), scanned, gap)
        return EndpointEventPage(tuple(selected), max(scanned, upper), gap)

    def wait_after(
        self,
        *,
        after: int,
        mode: ObservationLevel,
        timeout_seconds: float,
    ) -> EndpointEventPage:
        deadline = monotonic() + timeout_seconds
        with self._condition:
            while self._sequence <= after:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
        return self.replay(after=after, mode=mode)


def _level_rank(level: ObservationLevel) -> int:
    return {
        ObservationLevel.NORMAL: 0,
        ObservationLevel.VERBOSE: 1,
        ObservationLevel.MODEL: 2,
    }[level]
