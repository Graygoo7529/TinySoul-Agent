"""Runtime signal model."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.json import JsonObject, to_json_object

from ..scope import RunScope


@dataclass(frozen=True)
class Signal:
    """A structured signal used for module event propagation."""

    name: str
    source: str
    scope: RunScope
    payload: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Signal.name must be non-empty")
        if not self.source:
            raise ValueError("Signal.source must be non-empty")
        if not isinstance(self.scope, RunScope):
            raise TypeError("Signal.scope must be a RunScope")
        object.__setattr__(self, "payload", to_json_object(self.payload))

