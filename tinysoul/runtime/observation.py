"""Non-controlling runtime observation events and publisher protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import time
from typing import Protocol

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object

from .errors import RuntimeContractError
from .scope import RunScope


class ObservationLevel(StrEnum):
    """Increasing observation detail levels."""

    NORMAL = "normal"
    VERBOSE = "verbose"
    MODEL = "model"


@dataclass(frozen=True)
class ObservationEvent:
    """One immutable, provider-neutral runtime observation."""

    name: str
    level: ObservationLevel
    source: str
    scope: RunScope = field(default_factory=RunScope)
    message: str = ""
    payload: JsonObject = field(default_factory=dict)
    created_at: float = field(default_factory=time)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise RuntimeContractError("ObservationEvent.name must be non-empty")
        if not isinstance(self.level, ObservationLevel):
            raise RuntimeContractError(
                "ObservationEvent.level must be an ObservationLevel"
            )
        if not isinstance(self.source, str) or not self.source:
            raise RuntimeContractError("ObservationEvent.source must be non-empty")
        if not isinstance(self.scope, RunScope):
            raise RuntimeContractError("ObservationEvent.scope must be a RunScope")
        if not isinstance(self.message, str):
            raise RuntimeContractError("ObservationEvent.message must be a string")
        if isinstance(self.created_at, bool) or not isinstance(
            self.created_at,
            (int, float),
        ):
            raise RuntimeContractError("ObservationEvent.created_at must be numeric")
        try:
            payload = to_json_object(self.payload)
        except (JsonTypeError, RecursionError) as exc:
            raise RuntimeContractError(
                "ObservationEvent.payload must be a JSON object"
            ) from exc
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "created_at", float(self.created_at))


class ObservationEmitter(Protocol):
    """Fan-out boundary used by runtime and business orchestration modules."""

    def enabled(self, level: ObservationLevel) -> bool:
        """Return whether constructing an event at this level is useful."""
        ...

    def emit(self, event: ObservationEvent) -> None:
        """Publish an event without changing business control flow."""
        ...


@dataclass(frozen=True)
class NullObservationEmitter:
    """Default emitter for library use without an output boundary."""

    def enabled(self, level: ObservationLevel) -> bool:
        return False

    def emit(self, event: ObservationEvent) -> None:
        return


def emit_observation(
    emitter: ObservationEmitter,
    event: ObservationEvent,
) -> None:
    """Publish without allowing an observation adapter to alter business flow."""

    try:
        emitter.emit(event)
    except Exception:
        return


def observation_enabled(
    emitter: ObservationEmitter,
    level: ObservationLevel,
) -> bool:
    """Check interest without allowing an emitter failure into business flow."""

    try:
        return emitter.enabled(level)
    except Exception:
        return False
