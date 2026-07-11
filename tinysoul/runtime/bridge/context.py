"""Context-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.context.errors import (
    ContextBudgetError,
    ContextContractError,
    ContextInvariantError,
)
from tinysoul.context.failures import ContextFailureKind
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject

from ..exception import (
    CONTEXT_COMPRESSION_REQUIRED,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from ._payload import config_error_payload, exception_payload, runtime_exception

CONTEXT_RUNTIME_REASON_MAP: dict[ContextFailureKind, str] = {
    ContextFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    ContextFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    ContextFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
    ContextFailureKind.BUDGET_EXCEEDED: CONTEXT_COMPRESSION_REQUIRED,
}


@dataclass(frozen=True)
class RuntimeContextBridge:
    """Convert context boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: ContextFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="context",
            kind=kind,
            reason_map=CONTEXT_RUNTIME_REASON_MAP,
            message=message,
            payload=payload,
        )

    def from_exception(
        self,
        kind: ContextFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            kind,
            message=str(error),
            payload=exception_payload(error, payload),
        )

    def from_context_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        if isinstance(error, ContextBudgetError):
            budget_payload: JsonObject = {
                "estimated_chars": error.estimated_chars,
                "max_chars": error.max_chars,
                "estimated_image_bytes": error.estimated_image_bytes,
                "max_image_bytes": error.max_image_bytes,
            }
            if payload is not None:
                budget_payload = {**budget_payload, **payload}
            return self.from_exception(
                ContextFailureKind.BUDGET_EXCEEDED,
                error,
                payload=budget_payload,
            )
        kind = ContextFailureKind.INTERNAL_FAILURE
        if isinstance(error, (ContextContractError, ContextInvariantError)):
            kind = ContextFailureKind.CONTRACT_VIOLATION
        return self.from_exception(kind, error, payload=payload)

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            ContextFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            ContextFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=config_error_payload(error),
        )
