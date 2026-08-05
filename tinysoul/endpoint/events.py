"""Bounded replayable Endpoint observation stream."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Condition
from time import monotonic

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.runtime import ObservationEvent, ObservationLevel

from .errors import EndpointContractError, EndpointInvariantError
from .journal import EndpointEventJournal


@dataclass(frozen=True)
class EndpointEventEnvelope:
    sequence: int
    name: str
    level: ObservationLevel
    source: str
    scope: tuple[JsonObject, ...]
    message: str
    payload: JsonObject
    created_at: float
    size_bytes: int = field(repr=False)

    def to_json(self) -> JsonObject:
        return {
            "sequence": self.sequence,
            "name": self.name,
            "level": self.level.value,
            "source": self.source,
            "scope": list(self.scope),
            "message": self.message,
            "payload": self.payload,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class EndpointEventPage:
    events: tuple[EndpointEventEnvelope, ...]
    next_sequence: int
    gap: bool = False

    def to_json(self) -> JsonObject:
        return {
            "events": [event.to_json() for event in self.events],
            "next_sequence": self.next_sequence,
            "gap": self.gap,
        }


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
            record = to_json_object({
                "sequence": sequence,
                "name": event.name,
                "level": event.level.value,
                "source": event.source,
                "scope": list(scope),
                "message": event.message,
                "payload": event.payload,
                "created_at": event.created_at,
            })
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
    ) -> EndpointEventPage:
        if after < 0 or limit <= 0:
            raise EndpointContractError("Endpoint replay bounds are invalid")
        with self._condition:
            memory = tuple(self._events)
            sequence = self._sequence
            journal = self._journal
            page_bytes = self._page_bytes

        memory_oldest = memory[0].sequence if memory else sequence + 1
        retained_oldest = memory_oldest
        if journal is not None and not journal.degraded:
            journal_oldest = journal.oldest_sequence
            if journal_oldest is not None:
                retained_oldest = journal_oldest
        gap = after < retained_oldest - 1

        selected: list[EndpointEventEnvelope] = []
        used_bytes = 0

        def _accept(event: EndpointEventEnvelope) -> bool:
            nonlocal used_bytes
            if _level_rank(event.level) > _level_rank(mode):
                return True
            if selected and used_bytes + event.size_bytes > page_bytes:
                return False
            selected.append(event)
            used_bytes += event.size_bytes
            return len(selected) < limit

        need_journal = (
            journal is not None
            and not journal.degraded
            and after < memory_oldest - 1
        )
        if need_journal:
            journal_page = journal.read_after_page(
                after=after,
                mode=mode,
                limit=limit,
            )
            if journal.degraded:
                gap = gap or after < memory_oldest - 1
            reached_memory = False
            for event in journal_page.events:
                if event.sequence >= memory_oldest:
                    reached_memory = True
                    break
                if not _accept(event):
                    next_sequence = selected[-1].sequence if selected else after
                    return EndpointEventPage(
                        events=tuple(selected),
                        next_sequence=next_sequence,
                        gap=gap,
                    )
            # A journal page that stopped at its record limit has not reached
            # the memory boundary. Returning here preserves the byte/record
            # cursor instead of silently appending a later in-memory event.
            if not reached_memory and not journal_page.complete:
                next_sequence = selected[-1].sequence if selected else after
                return EndpointEventPage(
                    events=tuple(selected),
                    next_sequence=next_sequence,
                    gap=gap,
                )

        if len(selected) < limit and (
            not selected or used_bytes < page_bytes
        ):
            for event in memory:
                if event.sequence <= after:
                    continue
                if not _accept(event):
                    next_sequence = selected[-1].sequence if selected else after
                    return EndpointEventPage(
                        events=tuple(selected),
                        next_sequence=next_sequence,
                        gap=gap,
                    )

        next_sequence = selected[-1].sequence if selected else sequence
        return EndpointEventPage(
            events=tuple(selected),
            next_sequence=next_sequence,
            gap=gap,
        )

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
