"""JSON event envelopes and bounded idempotent asynchronous dispatch."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
from uuid import uuid4

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object


class EventProtocolError(Exception):
    """An environment event violated its admission contract."""


class EventCapacityError(EventProtocolError):
    """An event exceeds the bounded envelope size."""


class EventKind(StrEnum):
    EVENT = "event"
    TIMER = "timer"


@dataclass(frozen=True)
class EnvironmentEvent:
    kind: EventKind
    payload: JsonObject
    event_id: str = ""
    target_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EventKind):
            raise EventProtocolError("EnvironmentEvent.kind is invalid")
        try:
            payload = to_json_object(self.payload)
        except JsonTypeError as exc:
            raise EventProtocolError("EnvironmentEvent.payload requires JSON") from exc
        if not isinstance(self.event_id, str):
            raise EventProtocolError("EnvironmentEvent.event_id must be text")
        if self.target_id is not None and (not isinstance(self.target_id, str) or not self.target_id):
            raise EventProtocolError("EnvironmentEvent.target_id must be non-empty")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "event_id", self.event_id or f"event_{uuid4().hex}")


@dataclass(frozen=True)
class EventReceipt:
    sequence: int
    event_id: str
    delivered: bool


class EventBus:
    """Serialize delivery; retain bounded receipts, never a second event history."""

    def __init__(self, *, capacity: int = 256, max_event_bytes: int = 64_000) -> None:
        if any(type(value) is not int or value <= 0 for value in (capacity, max_event_bytes)):
            raise EventProtocolError("EventBus limits must be positive integers")
        self._capacity = capacity
        self._max_event_bytes = max_event_bytes
        self._receipts: OrderedDict[str, tuple[str, EventReceipt]] = OrderedDict()
        self._sequence = 0
        self._lock = asyncio.Lock()

    async def publish(
        self, event: EnvironmentEvent,
        *, deliver: Callable[[EnvironmentEvent], Awaitable[int]],
    ) -> EventReceipt:
        if not isinstance(event, EnvironmentEvent):
            raise EventProtocolError("EventBus requires an EnvironmentEvent")
        event = EnvironmentEvent(event.kind, event.payload, event.event_id, event.target_id)
        try:
            encoded = json.dumps(
                {"kind": event.kind.value, "payload": event.payload,
                 "id": event.event_id, "target": event.target_id},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise EventProtocolError("Environment event requires finite UTF-8 JSON") from exc
        if len(encoded) > self._max_event_bytes:
            raise EventCapacityError("Environment event exceeds admission size")
        digest = sha256(encoded).hexdigest()
        async with self._lock:
            existing = self._receipts.get(event.event_id)
            if existing is not None:
                if existing[0] != digest:
                    raise EventProtocolError("Event identity was reused with different content")
                return EventReceipt(existing[1].sequence, event.event_id, False)
            # Failed or cancelled delivery is retryable. Targets own idempotent
            # admission, including targets reached before a later target failed.
            count = await deliver(event)
            self._sequence += 1
            receipt = EventReceipt(self._sequence, event.event_id, count > 0)
            self._receipts[event.event_id] = (digest, receipt)
            while len(self._receipts) > self._capacity:
                self._receipts.popitem(last=False)
            return receipt
