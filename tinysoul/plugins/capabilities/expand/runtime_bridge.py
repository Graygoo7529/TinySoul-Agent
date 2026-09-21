"""Map MCP owner configuration and required process closure at the boundary."""

from tinysoul.infra.config import ConfigError
from tinysoul.runtime import RuntimeException
from tinysoul.runtime.control.exception import RUNTIME_STARTUP_FAILED, RUNTIME_AGENT_END
from tinysoul.runtime.failures import runtime_exception
from .failures import ExpandFailure


class RuntimeExpandBridge:
    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return runtime_exception(
            module="expand",
            kind=ExpandFailure.CONFIGURATION_FAILED,
            reason=RUNTIME_STARTUP_FAILED,
            message="MCP configuration is invalid.",
            payload={"error_type": type(error).__name__, "key": error.key},
        )

    def close_failed(self, error: Exception) -> RuntimeException:
        return runtime_exception(
            module="expand",
            kind=ExpandFailure.EXECUTION_CLOSE_FAILED,
            reason=RUNTIME_AGENT_END,
            message="MCP process could not be closed.",
            payload={"error_type": type(error).__name__},
        )
