"""LLM module semantic errors."""

from __future__ import annotations

from tinysoul.infra.json import JsonObject, to_json_object
from .failures import LLMFailureKind


class LLMError(Exception):
    """Base class for LLM module boundary errors."""


class LLMContractError(LLMError):
    """Raised when a caller or configuration violates the LLM contract."""


class LLMInvariantError(LLMError):
    """Raised when an internal LLM invariant is violated."""


class TaskCancelled(LLMError):
    """Raised when an owning execution boundary cancels an LLM task."""


class LLMInvocationFailure(LLMError):
    """Finite module failure that an operation may handle before Runtime."""

    def __init__(self, kind: LLMFailureKind, *, payload: JsonObject) -> None:
        super().__init__(kind.value)
        self.kind = kind
        self.payload = to_json_object(payload)

    @property
    def recoverable(self) -> bool:
        return (
            self.kind is LLMFailureKind.MODEL_CHAIN_EXHAUSTED
            and self.payload.get("provider_error_kind") == "transient"
        )
