"""Session-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.runtime.exception import (
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from tinysoul.runtime.failures import exception_payload, runtime_exception
from tinysoul.plugins.session.errors import (
    SessionContractError,
    SessionIOError,
    SessionInvariantError,
)
from tinysoul.plugins.session.failures import SessionFailureKind

SESSION_RUNTIME_REASON_MAP: dict[SessionFailureKind, str] = {
    SessionFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    SessionFailureKind.IO_FAILED: RUNTIME_TURN_END,
    SessionFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    SessionFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


SESSION_FAILURE_MESSAGES: dict[SessionFailureKind, str] = {
    SessionFailureKind.CONFIGURATION_FAILED: "Session configuration is invalid.",
    SessionFailureKind.IO_FAILED: "Session storage operation failed.",
    SessionFailureKind.CONTRACT_VIOLATION: "Session call violated its contract.",
    SessionFailureKind.INTERNAL_FAILURE: "Session operation failed internally.",
}


@dataclass(frozen=True)
class RuntimeSessionBridge:
    def from_failure(
        self,
        kind: SessionFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="session",
            kind=kind,
            reason=SESSION_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=payload,
        )

    def from_session_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = SessionFailureKind.INTERNAL_FAILURE
        if isinstance(error, SessionContractError):
            kind = SessionFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, SessionInvariantError):
            kind = SessionFailureKind.INTERNAL_FAILURE
        elif isinstance(error, SessionIOError):
            kind = SessionFailureKind.IO_FAILED
        return self.from_failure(
            kind,
            message=SESSION_FAILURE_MESSAGES[kind],
            payload=exception_payload(error, payload),
        )

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            SessionFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            SessionFailureKind.CONFIGURATION_FAILED,
            message=SESSION_FAILURE_MESSAGES[SessionFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
