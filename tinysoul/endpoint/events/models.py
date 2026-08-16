"""JSON-safe Endpoint Observation event models."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.json import JsonObject
from tinysoul.runtime import ObservationLevel


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
