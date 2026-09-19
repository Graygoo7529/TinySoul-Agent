"""Memory-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.plugins.memory.errors import (
    MemoryContractError,
    MemoryIOError,
    MemoryInvariantError,
)
from tinysoul.plugins.memory.failures import MemoryFailureKind
from tinysoul.runtime.control.exception import (
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from tinysoul.runtime.failures import exception_payload, runtime_exception

MEMORY_RUNTIME_REASON_MAP: dict[MemoryFailureKind, str] = {
    MemoryFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    MemoryFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    MemoryFailureKind.IO_FAILED: RUNTIME_TURN_END,
    MemoryFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


MEMORY_FAILURE_MESSAGES: dict[MemoryFailureKind, str] = {
    MemoryFailureKind.CONFIGURATION_FAILED: "Memory configuration is invalid.",
    MemoryFailureKind.CONTRACT_VIOLATION: "Memory call violated its contract.",
    MemoryFailureKind.IO_FAILED: "Memory storage operation failed.",
    MemoryFailureKind.INTERNAL_FAILURE: "Memory operation failed internally.",
}


@dataclass(frozen=True)
class RuntimeMemoryBridge:
    def from_failure(
        self,
        kind: MemoryFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="memory",
            kind=kind,
            reason=MEMORY_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=payload,
        )

    def from_memory_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = MemoryFailureKind.INTERNAL_FAILURE
        if isinstance(error, MemoryContractError):
            kind = MemoryFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, MemoryIOError):
            kind = MemoryFailureKind.IO_FAILED
        elif isinstance(error, MemoryInvariantError):
            kind = MemoryFailureKind.INTERNAL_FAILURE
        return self.from_failure(
            kind,
            message=MEMORY_FAILURE_MESSAGES[kind],
            payload=exception_payload(error, payload),
        )

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            MemoryFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            MemoryFailureKind.CONFIGURATION_FAILED,
            message=MEMORY_FAILURE_MESSAGES[MemoryFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
