"""Bounded replayable Endpoint observation stream."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Condition
from time import monotonic

from tinysoul.infra.json import JsonObject, dumps_json, to_json_object
from tinysoul.runtime import ObservationEvent, ObservationLevel

from .errors import EndpointContractError, EndpointInvariantError


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

    def __init__(self, *, capacity: int, max_bytes: int) -> None:
        if capacity <= 0 or max_bytes <= 0:
            raise EndpointContractError("Endpoint event bounds must be positive")
        self._capacity = capacity
        self._max_bytes = max_bytes
        self._events: deque[EndpointEventEnvelope] = deque()
        self._bytes = 0
        self._sequence = 0
        self._condition = Condition()

    @property
    def latest_sequence(self) -> int:
        with self._condition:
            return self._sequence

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
            oldest = self._events[0].sequence if self._events else self._sequence + 1
            gap = after < oldest - 1
            events = tuple(
                event
                for event in self._events
                if event.sequence > after and _level_rank(event.level) <= _level_rank(mode)
            )[:limit]
            next_sequence = events[-1].sequence if events else self._sequence
            return EndpointEventPage(
                events=events,
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
