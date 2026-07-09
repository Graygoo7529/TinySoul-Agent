"""Action-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.action.core.errors import ActionContractError, ActionInvariantError
from tinysoul.action.failures import ActionFailureKind
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from ._payload import config_error_payload, exception_payload, runtime_exception

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
        return runtime_exception(
            module="action",
            kind=kind,
            reason_map=ACTION_RUNTIME_REASON_MAP,
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
            message=str(error),
            payload=exception_payload(error, payload),
        )

    def from_action_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = ActionFailureKind.INTERNAL_FAILURE
        if isinstance(error, (ActionContractError, ActionInvariantError)):
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
            message=error.message,
            payload=config_error_payload(error),
        )
