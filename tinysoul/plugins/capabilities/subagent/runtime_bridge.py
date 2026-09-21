"""Only necessary configuration and execution-close failures enter Runtime."""

from tinysoul.infra.config import ConfigError
from tinysoul.runtime import RuntimeException
from tinysoul.runtime.control.exception import RUNTIME_STARTUP_FAILED, RUNTIME_AGENT_END
from tinysoul.runtime.failures import runtime_exception
from .failures import SubagentFailure


class RuntimeSubagentBridge:
    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return runtime_exception(
            module="subagent",
            kind=SubagentFailure.CONFIGURATION_FAILED,
            reason=RUNTIME_STARTUP_FAILED,
            message="External Agent configuration is invalid.",
            payload={"error_type": type(error).__name__, "key": error.key},
        )

    def close_failed(self, error: Exception) -> RuntimeException:
        return runtime_exception(
            module="subagent",
            kind=SubagentFailure.EXECUTION_CLOSE_FAILED,
            reason=RUNTIME_AGENT_END,
            message="External Agent execution could not be closed.",
            payload={"error_type": type(error).__name__},
        )
