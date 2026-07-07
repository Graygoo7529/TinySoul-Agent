"""Loop-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject, to_json_value
from tinysoul.loop.errors import LoopContractError, LoopInvariantError
from tinysoul.loop.failures import LoopFailureKind

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException

LOOP_RUNTIME_REASON_MAP: dict[LoopFailureKind, str] = {
    LoopFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    LoopFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    LoopFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


@dataclass(frozen=True)
class RuntimeLoopBridge:
    """Convert loop boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: LoopFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        runtime_payload: JsonObject = {}
        if payload is not None:
            runtime_payload = payload
        runtime_payload = {
            **runtime_payload,
            "module": "loop",
            "kind": kind.value,
        }
        return RuntimeException(
            reason=LOOP_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=runtime_payload,
        )

    def from_exception(
        self,
        kind: LoopFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        runtime_payload: JsonObject = {"error_type": type(error).__name__}
        if payload is not None:
            runtime_payload = {**runtime_payload, **payload}
        return self.from_failure(kind, message=str(error), payload=runtime_payload)

    def from_loop_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = LoopFailureKind.INTERNAL_FAILURE
        if isinstance(error, (LoopContractError, LoopInvariantError)):
            kind = LoopFailureKind.CONTRACT_VIOLATION
        return self.from_exception(kind, error, payload=payload)

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            LoopFailureKind.CONFIGURATION_FAILED,
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
            LoopFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=payload,
        )
