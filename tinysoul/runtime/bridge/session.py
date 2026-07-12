"""Session-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject
from tinysoul.session.errors import (
    SessionContractError,
    SessionIOError,
    SessionInvariantError,
)
from tinysoul.session.failures import SessionFailureKind

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from ._payload import config_error_payload, exception_payload, runtime_exception

SESSION_RUNTIME_REASON_MAP: dict[SessionFailureKind, str] = {
    SessionFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    SessionFailureKind.IO_FAILED: RUNTIME_TURN_END,
    SessionFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    SessionFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
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
            reason_map=SESSION_RUNTIME_REASON_MAP,
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
            SessionFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            SessionFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=config_error_payload(error),
        )
