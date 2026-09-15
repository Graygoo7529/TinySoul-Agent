"""Maintenance-owned mapping into generic Runtime failures."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.maintenance.errors import (
    MaintenanceContractError,
    MaintenanceInvariantError,
)
from tinysoul.maintenance.failures import MaintenanceFailureKind
from tinysoul.runtime import (
    RUNTIME_PROGRAM_END,
    RUNTIME_STARTUP_FAILED,
    RuntimeException,
)
from tinysoul.runtime.failures import exception_payload, runtime_exception


MAINTENANCE_RUNTIME_REASON_MAP: dict[MaintenanceFailureKind, str] = {
    MaintenanceFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    MaintenanceFailureKind.CONTRACT_VIOLATION: RUNTIME_PROGRAM_END,
    MaintenanceFailureKind.INVARIANT_VIOLATION: RUNTIME_PROGRAM_END,
}


MAINTENANCE_FAILURE_MESSAGES: dict[MaintenanceFailureKind, str] = {
    MaintenanceFailureKind.CONFIGURATION_FAILED: "Maintenance configuration is invalid.",
    MaintenanceFailureKind.CONTRACT_VIOLATION: "Maintenance call violated its contract.",
    MaintenanceFailureKind.INVARIANT_VIOLATION: "Maintenance state violated an invariant.",
}


@dataclass(frozen=True)
class MaintenanceRuntimeBridge:
    def from_failure(
        self,
        kind: MaintenanceFailureKind,
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
        kind = MaintenanceFailureKind.INVARIANT_VIOLATION
        if isinstance(error, MaintenanceContractError):
            kind = MaintenanceFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, MaintenanceInvariantError):
            kind = MaintenanceFailureKind.INVARIANT_VIOLATION
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
            MaintenanceFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            MaintenanceFailureKind.CONFIGURATION_FAILED,
            message=MAINTENANCE_FAILURE_MESSAGES[MaintenanceFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
