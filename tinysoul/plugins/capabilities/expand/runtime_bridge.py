"""Map MCP owner configuration and required process closure at the boundary."""

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.runtime import RuntimeException
from tinysoul.runtime.control.exception import RUNTIME_STARTUP_FAILED, RUNTIME_AGENT_END
from tinysoul.runtime.failures import exception_payload, runtime_exception
from .failures import ExpandFailureKind


EXPAND_RUNTIME_REASON_MAP = {
    ExpandFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    ExpandFailureKind.EXECUTION_CLOSE_FAILED: RUNTIME_AGENT_END,
}

EXPAND_FAILURE_MESSAGES = {
    ExpandFailureKind.CONFIGURATION_FAILED: "MCP configuration is invalid.",
    ExpandFailureKind.EXECUTION_CLOSE_FAILED: "MCP process could not be closed.",
}


@dataclass(frozen=True)
class RuntimeExpandBridge:
    def from_config_error(self, error: ConfigError) -> RuntimeException:
        kind = ExpandFailureKind.CONFIGURATION_FAILED
        return runtime_exception(
            module="expand",
            kind=kind,
            reason=EXPAND_RUNTIME_REASON_MAP[kind],
            message=EXPAND_FAILURE_MESSAGES[kind],
            payload=config_error_payload(error),
        )

    def close_failed(self, error: Exception) -> RuntimeException:
        kind = ExpandFailureKind.EXECUTION_CLOSE_FAILED
        return runtime_exception(
            module="expand",
            kind=kind,
            reason=EXPAND_RUNTIME_REASON_MAP[kind],
            message=EXPAND_FAILURE_MESSAGES[kind],
            payload=exception_payload(error),
        )
