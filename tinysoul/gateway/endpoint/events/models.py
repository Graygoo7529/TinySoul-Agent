"""JSON-safe Endpoint Observation event models."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.json import JsonObject
from tinysoul.runtime import ObservationLevel

from ..errors import EndpointContractError


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


@dataclass(frozen=True)
class EventFilter:
    turn_id: str | None = None
    task_id: str | None = None
    call_id: str | None = None
    search_id: str | None = None
    step_index: int | None = None
    through: int | None = None

    def __post_init__(self) -> None:
        if (
            self.step_index is not None
            and (self.search_id is None or self.step_index < 0)
            or self.through is not None
            and self.through < 0
        ):
            raise EndpointContractError("Event filter boundaries are invalid")

    def matches(self, event: EndpointEventEnvelope) -> bool:
        for key in ("turn_id", "task_id", "call_id", "search_id", "step_index"):
            expected = getattr(self, key)
            if expected is None:
                continue
            actual = event.payload.get(key)
            if key == "turn_id" and actual is None:
                actual = next(
                    (
                        frame["name"]
                        for frame in event.scope
                        if frame.get("level") == "turn"
                    ),
                    None,
                )
            if actual != expected:
                return False
        return True
