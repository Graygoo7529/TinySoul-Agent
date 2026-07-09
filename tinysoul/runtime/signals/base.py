"""Runtime signal model."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object

from ..errors import RuntimeContractError
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
            raise RuntimeContractError("Signal.name must be non-empty")
        if not self.source:
            raise RuntimeContractError("Signal.source must be non-empty")
        if not isinstance(self.scope, RunScope):
            raise RuntimeContractError("Signal.scope must be a RunScope")
        try:
            payload = to_json_object(self.payload)
        except JsonTypeError as exc:
            raise RuntimeContractError("Signal.payload must be a JSON object") from exc
        object.__setattr__(self, "payload", payload)
