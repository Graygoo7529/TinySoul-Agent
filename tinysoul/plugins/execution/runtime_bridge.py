"""Map execution configuration failures at the assembly boundary."""

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.runtime import RuntimeException
from tinysoul.runtime.control.exception import RUNTIME_STARTUP_FAILED
from tinysoul.runtime.failures import runtime_exception

from .failures import ExecutionFailureKind


EXECUTION_RUNTIME_REASON_MAP = {
    ExecutionFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
}

EXECUTION_FAILURE_MESSAGES = {
    ExecutionFailureKind.CONFIGURATION_FAILED: "Execution configuration is invalid.",
}


@dataclass(frozen=True)
class RuntimeExecutionBridge:
    def from_config_error(self, error: ConfigError) -> RuntimeException:
        kind = ExecutionFailureKind.CONFIGURATION_FAILED
        return runtime_exception(
            module="execution",
            kind=kind,
            reason=EXECUTION_RUNTIME_REASON_MAP[kind],
            message=EXECUTION_FAILURE_MESSAGES[kind],
            payload=config_error_payload(error),
        )
