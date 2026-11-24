"""Map Resource configuration and readiness failures at the startup boundary."""

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RuntimeException
from tinysoul.runtime.failures import runtime_exception

from .failures import ResourceFailureKind


RESOURCE_RUNTIME_REASON_MAP = {
    ResourceFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
}

RESOURCE_FAILURE_MESSAGES = {
    ResourceFailureKind.CONFIGURATION_FAILED: "Resource configuration is invalid.",
}


@dataclass(frozen=True)
class RuntimeResourceBridge:
    def from_config_error(self, error: ConfigError) -> RuntimeException:
        kind = ResourceFailureKind.CONFIGURATION_FAILED
        return runtime_exception(
            module="resource",
            kind=kind,
            reason=RESOURCE_RUNTIME_REASON_MAP[kind],
            message=RESOURCE_FAILURE_MESSAGES[kind],
            payload=config_error_payload(error),
        )
