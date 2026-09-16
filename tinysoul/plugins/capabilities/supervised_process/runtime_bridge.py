"""Shared supervised process-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.plugins.capabilities.supervised_process.errors import (
    SupervisedProcessContractError,
    SupervisedProcessExecutionError,
    SupervisedProcessStateError,
)
from tinysoul.plugins.capabilities.supervised_process.failures import (
    SupervisedProcessFailureKind,
)
from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.runtime.exception import (
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from tinysoul.runtime.failures import exception_payload, runtime_exception


SUPERVISED_PROCESS_RUNTIME_REASON_MAP: dict[
    SupervisedProcessFailureKind, str
] = {
    SupervisedProcessFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    SupervisedProcessFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    SupervisedProcessFailureKind.EXECUTION_FAILED: RUNTIME_TURN_END,
    SupervisedProcessFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


SUPERVISED_PROCESS_FAILURE_MESSAGES: dict[SupervisedProcessFailureKind, str] = {
    SupervisedProcessFailureKind.CONFIGURATION_FAILED: "Supervised process configuration is invalid.",
    SupervisedProcessFailureKind.CONTRACT_VIOLATION: "Supervised process call violated its contract.",
    SupervisedProcessFailureKind.EXECUTION_FAILED: "Supervised process execution failed.",
    SupervisedProcessFailureKind.INTERNAL_FAILURE: "Supervised process operation failed internally.",
}


@dataclass(frozen=True)
class RuntimeSupervisedProcessBridge:
    def from_failure(
        self,
        kind: SupervisedProcessFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="supervised_process",
            kind=kind,
            reason=SUPERVISED_PROCESS_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=payload,
        )

    def from_supervised_process_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = SupervisedProcessFailureKind.INTERNAL_FAILURE
        if isinstance(
            error,
            (SupervisedProcessContractError, SupervisedProcessStateError),
        ):
            kind = SupervisedProcessFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, SupervisedProcessExecutionError):
            kind = SupervisedProcessFailureKind.EXECUTION_FAILED
        return self.from_failure(
            kind,
            message=SUPERVISED_PROCESS_FAILURE_MESSAGES[kind],
            payload=exception_payload(error, payload),
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            SupervisedProcessFailureKind.CONFIGURATION_FAILED,
            message=SUPERVISED_PROCESS_FAILURE_MESSAGES[SupervisedProcessFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
