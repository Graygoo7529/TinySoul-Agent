"""Action-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.action.failures import ActionFailureKind
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject, to_json_value

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException

ACTION_RUNTIME_REASON_MAP: dict[ActionFailureKind, str] = {
    ActionFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    ActionFailureKind.CATALOG_FAILED: RUNTIME_STARTUP_FAILED,
    ActionFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    ActionFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


@dataclass(frozen=True)
class RuntimeActionBridge:
    """Convert action boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: ActionFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        runtime_payload: JsonObject = {}
        if payload is not None:
            runtime_payload = payload
        runtime_payload = {
            **runtime_payload,
            "module": "action",
            "kind": kind.value,
        }
        return RuntimeException(
            reason=ACTION_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=runtime_payload,
        )

    def from_exception(
        self,
        kind: ActionFailureKind,
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
            ActionFailureKind.CONFIGURATION_FAILED,
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
            ActionFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=payload,
        )
