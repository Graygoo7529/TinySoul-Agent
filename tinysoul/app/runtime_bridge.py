"""App-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.app.errors import AppContractError
from tinysoul.app.failures import AppFailureKind
from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.runtime.exception import (
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from tinysoul.runtime.failures import exception_payload, runtime_exception

APP_RUNTIME_REASON_MAP: dict[AppFailureKind, str] = {
    AppFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    AppFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    AppFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


APP_FAILURE_MESSAGES: dict[AppFailureKind, str] = {
    AppFailureKind.CONFIGURATION_FAILED: "App configuration is invalid.",
    AppFailureKind.CONTRACT_VIOLATION: "App call violated its contract.",
    AppFailureKind.INTERNAL_FAILURE: "App operation failed internally.",
}


@dataclass(frozen=True)
class RuntimeAppBridge:
    """Convert app boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: AppFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="app",
            kind=kind,
            reason=APP_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=payload,
        )

    def from_exception(
        self,
        kind: AppFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            kind,
            message=APP_FAILURE_MESSAGES[kind],
            payload=exception_payload(error, payload),
        )

    def from_app_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = AppFailureKind.INTERNAL_FAILURE
        if isinstance(error, AppContractError):
            kind = AppFailureKind.CONTRACT_VIOLATION
        return self.from_exception(kind, error, payload=payload)

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            AppFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            AppFailureKind.CONFIGURATION_FAILED,
            message=APP_FAILURE_MESSAGES[AppFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
