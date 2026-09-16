"""Context-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.kernel.context.errors import (
    ContextBudgetError,
    ContextContractError,
    ContextInvariantError,
)
from tinysoul.kernel.context.failures import ContextFailureKind, CONTEXT_COMPRESSION_REQUIRED
from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from tinysoul.runtime.failures import exception_payload, runtime_exception

CONTEXT_RUNTIME_REASON_MAP: dict[ContextFailureKind, str] = {
    ContextFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    ContextFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    ContextFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
    ContextFailureKind.BUDGET_EXCEEDED: CONTEXT_COMPRESSION_REQUIRED,
}


CONTEXT_FAILURE_MESSAGES: dict[ContextFailureKind, str] = {
    ContextFailureKind.CONFIGURATION_FAILED: "Context configuration is invalid.",
    ContextFailureKind.CONTRACT_VIOLATION: "Context call violated its contract.",
    ContextFailureKind.INTERNAL_FAILURE: "Context operation failed internally.",
    ContextFailureKind.BUDGET_EXCEEDED: "Context exceeds its capacity budget.",
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
            reason=CONTEXT_RUNTIME_REASON_MAP[kind],
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
            message=CONTEXT_FAILURE_MESSAGES[kind],
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
                "estimated_image_bytes": error.estimated_image_bytes,
                "max_image_bytes": error.max_image_bytes,
                "section_usage": error.section_usage,
            }
            if payload is not None:
                budget_payload = {**budget_payload, **payload}
            return self.from_exception(
                ContextFailureKind.BUDGET_EXCEEDED,
                error,
                payload=budget_payload,
            )
        kind = ContextFailureKind.INTERNAL_FAILURE
        if isinstance(error, ContextContractError):
            kind = ContextFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, ContextInvariantError):
            kind = ContextFailureKind.INTERNAL_FAILURE
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
            message=CONTEXT_FAILURE_MESSAGES[ContextFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
