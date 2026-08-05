"""Stable Turn outcome status and bounded failure details."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tinysoul.runtime import (
    RUNTIME_CYCLE_END,
    RUNTIME_PROGRAM_END,
    RUNTIME_TURN_END,
    RuntimeException,
)
from tinysoul.infra.json import JsonObject, to_json_object

from .errors import LoopContractError

TURN_FAILURE_MESSAGE_MAX_CHARS = 1000
TURN_FAILURE_FEEDBACK_MAX_ITEMS = 8
TURN_FAILURE_FEEDBACK_MAX_CHARS = 2000


@dataclass(frozen=True)
class TurnOutput:
    """Validated user-facing output produced by a completed Turn."""

    text: str
    result_id: str
    references: tuple[str, ...] = ()
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text:
            raise LoopContractError("TurnOutput.text must be non-empty")
        if not self.result_id:
            raise LoopContractError("TurnOutput.result_id must be non-empty")
        for reference in self.references:
            if not isinstance(reference, str) or not reference:
                raise LoopContractError(
                    "TurnOutput.references must contain non-empty strings"
                )
        object.__setattr__(self, "references", tuple(self.references))
        object.__setattr__(self, "metadata", to_json_object(self.metadata))


class TurnOutcomeStatus(StrEnum):
    ANSWERED = "answered"
    COMPLETED = "completed"
    EXHAUSTED = "exhausted"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class TurnFailure:
    reason: str
    message: str
    module: str = ""
    kind: str = ""
    feedback: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason:
            raise LoopContractError("TurnFailure.reason must be non-empty")
        if not isinstance(self.message, str) or not self.message:
            raise LoopContractError("TurnFailure requires reason and message")
        if not isinstance(self.module, str) or not isinstance(self.kind, str):
            raise LoopContractError("TurnFailure module and kind must be strings")
        if any(not isinstance(item, str) for item in self.feedback):
            raise LoopContractError("TurnFailure.feedback must contain strings")
        feedback: list[str] = []
        used = 0
        for item in self.feedback:
            if not item or len(feedback) >= TURN_FAILURE_FEEDBACK_MAX_ITEMS:
                continue
            remaining = TURN_FAILURE_FEEDBACK_MAX_CHARS - used
            if remaining <= 0:
                break
            clipped = item[:remaining]
            feedback.append(clipped)
            used += len(clipped)
        object.__setattr__(self, "feedback", tuple(feedback))
        if len(self.message) > TURN_FAILURE_MESSAGE_MAX_CHARS:
            object.__setattr__(
                self,
                "message",
                self.message[: TURN_FAILURE_MESSAGE_MAX_CHARS - 3] + "...",
            )

    @classmethod
    def from_runtime(cls, exc: RuntimeException) -> "TurnFailure":
        module = exc.payload.get("module", "")
        kind = exc.payload.get("kind", "")
        feedback_raw = exc.payload.get("feedback", ())
        feedback = (
            tuple(item for item in feedback_raw if isinstance(item, str))
            if isinstance(feedback_raw, (list, tuple))
            else ()
        )
        return cls(
            reason=exc.reason,
            message=exc.message or exc.reason,
            module=module if isinstance(module, str) else "",
            kind=kind if isinstance(kind, str) else "",
            feedback=feedback,
        )


def failure_from_runtime(exc: RuntimeException) -> TurnFailure | None:
    """Return failure details only for Runtime exceptions that mean failure."""

    if exc.reason in {
        RUNTIME_CYCLE_END,
        RUNTIME_PROGRAM_END,
    }:
        return None
    if exc.reason == RUNTIME_TURN_END and not (
        isinstance(exc.payload.get("module"), str)
        and exc.payload.get("module")
        and isinstance(exc.payload.get("kind"), str)
        and exc.payload.get("kind")
    ):
        return None
    return TurnFailure.from_runtime(exc)
