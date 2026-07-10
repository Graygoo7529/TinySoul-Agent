"""Runtime exceptions that are allowed to cross module boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field

from tinysoul.infra.json import JsonObject, JsonTypeError, to_json_object

from .errors import RuntimeContractError

RUNTIME_STARTUP_FAILED = "runtime.startup_failed"
RUNTIME_TURN_END = "runtime.turn_end"
RUNTIME_CYCLE_END = "runtime.cycle_end"
RUNTIME_PROGRAM_END = "runtime.program_end"
RUNTIME_TURN_OUTPUT = "runtime.turn_output"
CONTEXT_COMPRESSION_REQUIRED = "context.compression_required"
HOME_RUNTIME_COPY_REQUIRED = "home.runtime_copy_required"


@dataclass
class RuntimeException(Exception):
    """A stable runtime-level exception with a handler reason."""

    reason: str
    message: str
    payload: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason:
            raise RuntimeContractError("RuntimeException.reason must be non-empty")
        try:
            payload = to_json_object(self.payload)
        except JsonTypeError as exc:
            raise RuntimeContractError(
                "RuntimeException.payload must be a JSON object"
            ) from exc
        object.__setattr__(self, "payload", payload)

    def __str__(self) -> str:
        if self.message:
            return f"{self.reason}: {self.message}"
        return self.reason
