"""Bounded, non-controlling observation streams for embedded consumers."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, replace
from threading import RLock
from typing import Self

from tinysoul.infra.json import dumps_json, to_json_object
from tinysoul.runtime import ObservationEvent, ObservationLevel, RunLevel

from .errors import AgentClosedError, AgentSDKError


@dataclass(frozen=True)
class ObservationFilter:
    level: ObservationLevel = ObservationLevel.NORMAL
    names: tuple[str, ...] = ()
    turn_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.level, ObservationLevel):
            raise AgentSDKError("Observation filter requires a typed level")
        if not isinstance(self.turn_id, str) or any(not isinstance(name, str) or not name for name in self.names):
            raise AgentSDKError("Observation filter identities must be text")
        object.__setattr__(self, "names", tuple(self.names))

    def accepts(self, event: ObservationEvent) -> bool:
        turn = event.scope.nearest(RunLevel.TURN)
        return (
            tuple(ObservationLevel).index(event.level) <= tuple(ObservationLevel).index(self.level)
            and (not self.names or event.name in self.names)
            and (not self.turn_id or (turn is not None and turn.name == self.turn_id))
        )


@dataclass(frozen=True)
class ObservationRecord:
    sequence: int
    event: ObservationEvent

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1 or not isinstance(self.event, ObservationEvent):
            raise AgentSDKError("Observation record requires a positive sequence and event")


@dataclass(frozen=True)
class ObservationGap:
    first_sequence: int
    last_sequence: int
    dropped_count: int

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in (self.first_sequence, self.last_sequence, self.dropped_count)):
            raise AgentSDKError("Observation gap requires integer bounds")
        if not 1 <= self.dropped_count <= self.last_sequence - self.first_sequence + 1 or self.first_sequence < 1:
            raise AgentSDKError("Observation gap has invalid bounds")


class ObservationSubscription:
    """A single-reader stream; cancellation of a read does not cancel the Agent."""

    def __init__(
        self, hub: ObservationSubscriptions, selection: ObservationFilter,
        *, capacity: int, max_bytes: int,
    ) -> None:
        self._hub = hub
        self._selection = selection
        self._capacity = capacity
        self._max_bytes = max_bytes
        self._records: deque[tuple[ObservationRecord, int]] = deque()
        self._bytes = 0
        self._gap: ObservationGap | None = None
        self._loop = asyncio.get_running_loop()
        self._ready = asyncio.Event()
        self._lock = RLock()
        self._notified = False
        self._closed = False
        self._reading = False

    @property
    def selection(self) -> ObservationFilter:
        return self._selection

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> ObservationRecord | ObservationGap:
        if self._reading:
            raise AgentSDKError("Observation subscription supports one reader")
        self._reading = True
        try:
            while True:
                with self._lock:
                    if self._gap is not None:
                        gap, self._gap = self._gap, None
                        return gap
                    if self._records:
                        record, size = self._records.popleft()
                        self._bytes -= size
                        return record
                    if self._closed:
                        raise StopAsyncIteration
                    self._ready.clear()
                await self._ready.wait()
        finally:
            self._reading = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self._hub.remove(self)
        self.finish(discard=True)

    def finish(self, *, discard: bool = False) -> None:
        with self._lock:
            self._closed = True
            if discard:
                self._records.clear()
                self._bytes = 0
                self._gap = None
            self._notify()

    def offer(self, record: ObservationRecord, size: int) -> None:
        with self._lock:
            if self._closed or not self.selection.accepts(record.event):
                return
            while self._records and (len(self._records) >= self._capacity or self._bytes + size > self._max_bytes):
                lost, lost_size = self._records.popleft()
                self._bytes -= lost_size
                self._drop(lost.sequence)
            if size > self._max_bytes:
                self._drop(record.sequence)
            else:
                # Each subscription owns its event payload; consumers cannot mutate peers.
                self._records.append((replace(
                    record,
                    event=replace(record.event, payload=to_json_object(record.event.payload)),
                ), size))
                self._bytes += size
            self._notify()

    def _drop(self, sequence: int) -> None:
        previous = self._gap
        self._gap = ObservationGap(
            previous.first_sequence if previous is not None else sequence,
            sequence, previous.dropped_count + 1 if previous is not None else 1,
        )

    def _notify(self) -> None:
        # At most one callback per subscriber, even under a fast worker-thread producer.
        if self._notified or self._loop.is_closed():
            return
        self._notified = True
        try:
            self._loop.call_soon_threadsafe(self._wake)
        except RuntimeError:
            # The embedding loop may close between the check and scheduling.
            self._notified = False
            self._closed = True

    def _wake(self) -> None:
        with self._lock:
            self._notified = False
            self._ready.set()


class ObservationSubscriptions:
    """One Agent's bounded set of subscriptions, independent of business state."""

    def __init__(self, *, max_subscribers: int = 32) -> None:
        if type(max_subscribers) is not int or max_subscribers < 1:
            raise AgentSDKError("Observation subscriber limit must be positive")
        self._limit = max_subscribers
        self._subscriptions: set[ObservationSubscription] = set()
        self._sequence = 0
        self._closed = False
        self._lock = RLock()

    def subscribe(
        self, selection: ObservationFilter = ObservationFilter(), *,
        capacity: int = 256, max_bytes: int = 1024 * 1024,
    ) -> ObservationSubscription:
        if type(capacity) is not int or type(max_bytes) is not int or capacity < 1 or max_bytes < 1:
            raise AgentSDKError("Observation capacity and byte limit must be positive")
        if not isinstance(selection, ObservationFilter):
            raise AgentSDKError("Observation selection must be typed")
        with self._lock:
            if self._closed:
                raise AgentClosedError("Observation source is closed")
            if len(self._subscriptions) >= self._limit:
                raise AgentSDKError("Observation subscriber limit reached")
            subscription = ObservationSubscription(self, selection, capacity=capacity, max_bytes=max_bytes)
            self._subscriptions.add(subscription)
            return subscription

    def enabled(self, level: ObservationLevel) -> bool:
        with self._lock:
            return any(tuple(ObservationLevel).index(level) <= tuple(ObservationLevel).index(item.selection.level)
                       for item in self._subscriptions)

    def write(self, event: ObservationEvent) -> None:
        with self._lock:
            if self._closed or not self._subscriptions:
                return
            self._sequence += 1
            record = ObservationRecord(self._sequence, event)
            size = len(dumps_json({"name": event.name, "source": event.source, "message": event.message,
                                   "payload": event.payload, "level": event.level.value,
                                   "created_at": event.created_at,
                                   "scope": [{"level": frame.level.value, "name": frame.name} for frame in event.scope],
                                   "sequence": record.sequence}).encode("utf-8"))
            for subscription in self._subscriptions:
                subscription.offer(record, size)

    def remove(self, subscription: ObservationSubscription) -> None:
        with self._lock:
            self._subscriptions.discard(subscription)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for subscription in self._subscriptions:
                subscription.finish()
            self._subscriptions.clear()
