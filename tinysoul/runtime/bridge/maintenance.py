"""Maintenance-to-Runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.maintenance.errors import (
    MaintenanceContractError,
    MaintenanceInvariantError,
)
from tinysoul.maintenance.failures import MaintenanceFailureKind

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from ._payload import config_error_payload, exception_payload, runtime_exception


MAINTENANCE_RUNTIME_REASON_MAP: dict[MaintenanceFailureKind, str] = {
    MaintenanceFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    MaintenanceFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    MaintenanceFailureKind.INVARIANT_VIOLATION: RUNTIME_TURN_END,
}


@dataclass(frozen=True)
class RuntimeMaintenanceBridge:
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
            reason_map=MAINTENANCE_RUNTIME_REASON_MAP,
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
            MaintenanceFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            MaintenanceFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=config_error_payload(error),
        )
