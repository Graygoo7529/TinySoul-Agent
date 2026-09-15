"""Shell capability-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.capabilities.shell.errors import ShellContractError
from tinysoul.capabilities.shell.failures import ShellFailureKind
from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.runtime.exception import (
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from tinysoul.runtime.failures import exception_payload, runtime_exception


SHELL_RUNTIME_REASON_MAP: dict[ShellFailureKind, str] = {
    ShellFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    ShellFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    ShellFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


SHELL_FAILURE_MESSAGES: dict[ShellFailureKind, str] = {
    ShellFailureKind.CONFIGURATION_FAILED: "Shell configuration is invalid.",
    ShellFailureKind.CONTRACT_VIOLATION: "Shell call violated its contract.",
    ShellFailureKind.INTERNAL_FAILURE: "Shell operation failed internally.",
}


@dataclass(frozen=True)
class RuntimeShellBridge:
    def from_failure(
        self,
        kind: ShellFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="shell",
            kind=kind,
            reason=SHELL_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=payload,
        )

    def from_shell_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = ShellFailureKind.INTERNAL_FAILURE
        if isinstance(error, ShellContractError):
            kind = ShellFailureKind.CONTRACT_VIOLATION
        return self.from_failure(
            kind,
            message=SHELL_FAILURE_MESSAGES[kind],
            payload=exception_payload(error, payload),
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            ShellFailureKind.CONFIGURATION_FAILED,
            message=SHELL_FAILURE_MESSAGES[ShellFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
