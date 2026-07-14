"""Memory-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.memory.errors import (
    MemoryContractError,
    MemoryIOError,
    MemoryInvariantError,
)
from tinysoul.memory.failures import MemoryFailureKind

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from ._payload import config_error_payload, exception_payload, runtime_exception


MEMORY_RUNTIME_REASON_MAP: dict[MemoryFailureKind, str] = {
    MemoryFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    MemoryFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    MemoryFailureKind.IO_FAILED: RUNTIME_TURN_END,
    MemoryFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
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
            reason_map=MEMORY_RUNTIME_REASON_MAP,
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
            message=str(error),
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
            message=error.message,
            payload=config_error_payload(error),
        )
