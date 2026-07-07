"""App-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.app.errors import AppContractError, AppInvariantError
from tinysoul.app.failures import AppFailureKind
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject, to_json_value

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException

APP_RUNTIME_REASON_MAP: dict[AppFailureKind, str] = {
    AppFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    AppFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    AppFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
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
        runtime_payload: JsonObject = {}
        if payload is not None:
            runtime_payload = payload
        runtime_payload = {
            **runtime_payload,
            "module": "app",
            "kind": kind.value,
        }
        return RuntimeException(
            reason=APP_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=runtime_payload,
        )

    def from_exception(
        self,
        kind: AppFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        runtime_payload: JsonObject = {"error_type": type(error).__name__}
        if payload is not None:
            runtime_payload = {**runtime_payload, **payload}
        return self.from_failure(kind, message=str(error), payload=runtime_payload)

    def from_app_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = AppFailureKind.INTERNAL_FAILURE
        if isinstance(error, (AppContractError, AppInvariantError)):
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
        payload: JsonObject = {
            "key": error.key,
            "source": error.source,
            "expected": error.expected,
        }
        if error.value is not None:
            payload = {**payload, "value": to_json_value(error.value)}
        return self.from_failure(
            AppFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=payload,
        )
