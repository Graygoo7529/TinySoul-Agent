"""Runtime exceptions that are allowed to cross module boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.json import JsonObject, to_json_object

RUNTIME_STARTUP_FAILED = "runtime.startup_failed"
RUNTIME_UNHANDLED_FAILURE = "runtime.unhandled_failure"
RUNTIME_TURN_END_REQUESTED = "runtime.turn_end_requested"
RUNTIME_CYCLE_END_REQUESTED = "runtime.cycle_end_requested"
PROGRAM_END_REQUESTED = "runtime.program_end_requested"
CONTEXT_COMPRESSION_REQUIRED = "context.compression_required"
HOME_RUNTIME_COPY_REQUIRED = "home.runtime_copy_required"


@dataclass(frozen=True)
class RuntimeException(Exception):
    """A stable runtime-level exception with a handler reason."""

    reason: str
    message: str
    payload: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("reason must be non-empty")
        object.__setattr__(self, "payload", to_json_object(self.payload))

    def __str__(self) -> str:
        if self.message:
            return f"{self.reason}: {self.message}"
        return self.reason
