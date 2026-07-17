"""Script capability-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.capabilities.script.errors import (
    ScriptContractError,
    ScriptExecutionError,
    ScriptPolicyError,
    ScriptStateError,
)
from tinysoul.capabilities.script.failures import ScriptFailureKind
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from ._payload import config_error_payload, exception_payload, runtime_exception


SCRIPT_RUNTIME_REASON_MAP: dict[ScriptFailureKind, str] = {
    ScriptFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    ScriptFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    ScriptFailureKind.EXECUTION_FAILED: RUNTIME_TURN_END,
    ScriptFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


@dataclass(frozen=True)
class RuntimeScriptBridge:
    """Convert non-Action Script failures into Runtime semantic exceptions."""

    def from_failure(
        self,
        kind: ScriptFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="script",
            kind=kind,
            reason_map=SCRIPT_RUNTIME_REASON_MAP,
            message=message,
            payload=payload,
        )

    def from_script_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = ScriptFailureKind.INTERNAL_FAILURE
        if isinstance(error, (ScriptContractError, ScriptPolicyError, ScriptStateError)):
            kind = ScriptFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, ScriptExecutionError):
            kind = ScriptFailureKind.EXECUTION_FAILED
        return self.from_failure(
            kind,
            message=str(error),
            payload=exception_payload(error, payload),
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            ScriptFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=config_error_payload(error),
        )
