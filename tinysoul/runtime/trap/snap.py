"""Trap snapshot context."""

from __future__ import annotations

from dataclasses import dataclass, field
import traceback

from tinysoul.infra.json import JsonObject, to_json_object

from ..exception import RuntimeException
from ..scope import RunScope


@dataclass(frozen=True)
class TrapSnap:
    """A snapshot captured by the trap from a runtime exception."""

    reason: str
    message: str
    payload: JsonObject = field(default_factory=dict)
    scope: RunScope = field(default_factory=RunScope)
    traceback_text: str | None = None

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("TrapSnap.reason must be non-empty")
        object.__setattr__(self, "payload", to_json_object(self.payload))
        if not isinstance(self.scope, RunScope):
            raise TypeError("TrapSnap.scope must be a RunScope")

    @classmethod
    def from_exception(
        cls,
        exception: RuntimeException,
        scope: RunScope,
    ) -> "TrapSnap":
        traceback_text = None
        if exception.__traceback__ is not None:
            traceback_text = "".join(
                traceback.format_exception(
                    type(exception),
                    exception,
                    exception.__traceback__,
                )
            )
        return cls(
            reason=exception.reason,
            message=exception.message,
            payload=exception.payload,
            scope=scope,
            traceback_text=traceback_text,
        )
