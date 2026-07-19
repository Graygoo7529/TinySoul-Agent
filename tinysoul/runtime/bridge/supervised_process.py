"""Shared supervised process-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.capabilities.supervised_process.errors import (
    SupervisedProcessContractError,
    SupervisedProcessExecutionError,
    SupervisedProcessStateError,
)
from tinysoul.capabilities.supervised_process.failures import (
    SupervisedProcessFailureKind,
)
from tinysoul.infra.json import JsonObject
from tinysoul.infra.config import ConfigError

from ..exception import RUNTIME_STARTUP_FAILED, RUNTIME_TURN_END, RuntimeException
from ._payload import config_error_payload, exception_payload, runtime_exception


SUPERVISED_PROCESS_RUNTIME_REASON_MAP: dict[
    SupervisedProcessFailureKind, str
] = {
    SupervisedProcessFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    SupervisedProcessFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    SupervisedProcessFailureKind.EXECUTION_FAILED: RUNTIME_TURN_END,
    SupervisedProcessFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
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
            reason_map=SUPERVISED_PROCESS_RUNTIME_REASON_MAP,
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
            message=str(error),
            payload=exception_payload(error, payload),
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            SupervisedProcessFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=config_error_payload(error),
        )
