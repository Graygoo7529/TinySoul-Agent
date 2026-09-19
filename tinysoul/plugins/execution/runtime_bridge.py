"""Map execution configuration failures at the assembly boundary."""

from tinysoul.infra.config import ConfigError
from tinysoul.runtime import RuntimeException
from tinysoul.runtime.control.exception import RUNTIME_STARTUP_FAILED
from tinysoul.runtime.failures import runtime_exception

from .failures import ExecutionFailureKind


class RuntimeExecutionBridge:
    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return runtime_exception(
            module="execution",
            kind=ExecutionFailureKind.CONFIGURATION_FAILED,
            reason=RUNTIME_STARTUP_FAILED,
            message="Execution configuration is invalid.",
            payload={"error_type": type(error).__name__, "key": error.key},
        )
