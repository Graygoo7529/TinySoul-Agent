"""Reflection-owned mapping into generic Runtime failures."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.plugins.reflection.errors import (
    ReflectionContractError,
    ReflectionInvariantError,
)
from tinysoul.plugins.reflection.failures import ReflectionFailureKind
from tinysoul.runtime import (
    RUNTIME_AGENT_END,
    RUNTIME_STARTUP_FAILED,
    RuntimeException,
)
from tinysoul.runtime.failures import exception_payload, runtime_exception


MAINTENANCE_RUNTIME_REASON_MAP: dict[ReflectionFailureKind, str] = {
    ReflectionFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    ReflectionFailureKind.CONTRACT_VIOLATION: RUNTIME_AGENT_END,
    ReflectionFailureKind.INVARIANT_VIOLATION: RUNTIME_AGENT_END,
}


MAINTENANCE_FAILURE_MESSAGES: dict[ReflectionFailureKind, str] = {
    ReflectionFailureKind.CONFIGURATION_FAILED: "Reflection configuration is invalid.",
    ReflectionFailureKind.CONTRACT_VIOLATION: "Reflection call violated its contract.",
    ReflectionFailureKind.INVARIANT_VIOLATION: "Reflection state violated an invariant.",
}


@dataclass(frozen=True)
class ReflectionRuntimeBridge:
    def from_failure(
        self,
        kind: ReflectionFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="maintenance",
            kind=kind,
            reason=MAINTENANCE_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=payload,
        )

    def from_maintenance_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = ReflectionFailureKind.INVARIANT_VIOLATION
        if isinstance(error, ReflectionContractError):
            kind = ReflectionFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, ReflectionInvariantError):
            kind = ReflectionFailureKind.INVARIANT_VIOLATION
        return self.from_failure(
            kind,
            message=MAINTENANCE_FAILURE_MESSAGES[kind],
            payload=exception_payload(error, payload),
        )

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            ReflectionFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            ReflectionFailureKind.CONFIGURATION_FAILED,
            message=MAINTENANCE_FAILURE_MESSAGES[ReflectionFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
