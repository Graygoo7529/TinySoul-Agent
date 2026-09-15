"""Action-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.action.core.errors import ActionContractError
from tinysoul.action.failures import ActionFailureKind
from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.runtime.exception import (
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from tinysoul.runtime.failures import exception_payload, runtime_exception

ACTION_RUNTIME_REASON_MAP: dict[ActionFailureKind, str] = {
    ActionFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    ActionFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    ActionFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


ACTION_FAILURE_MESSAGES: dict[ActionFailureKind, str] = {
    ActionFailureKind.CONFIGURATION_FAILED: "Action configuration is invalid.",
    ActionFailureKind.CONTRACT_VIOLATION: "Action call violated its contract.",
    ActionFailureKind.INTERNAL_FAILURE: "Action operation failed internally.",
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
        return runtime_exception(
            module="action",
            kind=kind,
            reason=ACTION_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=payload,
        )

    def from_exception(
        self,
        kind: ActionFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            kind,
            message=ACTION_FAILURE_MESSAGES[kind],
            payload=exception_payload(error, payload),
        )

    def from_action_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = ActionFailureKind.INTERNAL_FAILURE
        if isinstance(error, ActionContractError):
            kind = ActionFailureKind.CONTRACT_VIOLATION
        return self.from_exception(kind, error, payload=payload)

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
        return self.from_failure(
            ActionFailureKind.CONFIGURATION_FAILED,
            message=ACTION_FAILURE_MESSAGES[ActionFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
