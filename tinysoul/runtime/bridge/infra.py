"""Infra-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.failures import InfraFailureKind
from tinysoul.infra.json import JsonObject, to_json_value

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException

INFRA_RUNTIME_REASON_MAP: dict[InfraFailureKind, str] = {
    InfraFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    InfraFailureKind.JSON_BOUNDARY_FAILED: RUNTIME_TURN_END,
    InfraFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    InfraFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


@dataclass(frozen=True)
class RuntimeInfraBridge:
    """Convert infra boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: InfraFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        runtime_payload: JsonObject = {}
        if payload is not None:
            runtime_payload = payload
        runtime_payload = {
            **runtime_payload,
            "module": "infra",
            "kind": kind.value,
        }
        return RuntimeException(
            reason=INFRA_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=runtime_payload,
        )

    def from_exception(
        self,
        kind: InfraFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        runtime_payload: JsonObject = {"error_type": type(error).__name__}
        if payload is not None:
            runtime_payload = {**runtime_payload, **payload}
        return self.from_failure(kind, message=str(error), payload=runtime_payload)

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            InfraFailureKind.CONFIGURATION_FAILED,
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
            InfraFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=payload,
        )
