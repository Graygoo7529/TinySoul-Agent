"""Only necessary configuration and execution-close failures enter Runtime."""

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.runtime import RuntimeException
from tinysoul.runtime.control.exception import RUNTIME_STARTUP_FAILED, RUNTIME_AGENT_END
from tinysoul.runtime.failures import exception_payload, runtime_exception
from .failures import SubagentFailureKind


SUBAGENT_RUNTIME_REASON_MAP = {
    SubagentFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    SubagentFailureKind.EXECUTION_CLOSE_FAILED: RUNTIME_AGENT_END,
}

SUBAGENT_FAILURE_MESSAGES = {
    SubagentFailureKind.CONFIGURATION_FAILED: "External Agent configuration is invalid.",
    SubagentFailureKind.EXECUTION_CLOSE_FAILED: "External Agent execution could not be closed.",
}


@dataclass(frozen=True)
class RuntimeSubagentBridge:
    def from_config_error(self, error: ConfigError) -> RuntimeException:
        kind = SubagentFailureKind.CONFIGURATION_FAILED
        return runtime_exception(
            module="subagent",
            kind=kind,
            reason=SUBAGENT_RUNTIME_REASON_MAP[kind],
            message=SUBAGENT_FAILURE_MESSAGES[kind],
            payload=config_error_payload(error),
        )

    def close_failed(self, error: Exception) -> RuntimeException:
        kind = SubagentFailureKind.EXECUTION_CLOSE_FAILED
        return runtime_exception(
            module="subagent",
            kind=kind,
            reason=SUBAGENT_RUNTIME_REASON_MAP[kind],
            message=SUBAGENT_FAILURE_MESSAGES[kind],
            payload=exception_payload(error),
        )
