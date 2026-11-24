"""Map Web configuration and readiness failures at the startup boundary."""

from dataclasses import dataclass

from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.runtime import RUNTIME_STARTUP_FAILED, RuntimeException
from tinysoul.runtime.failures import runtime_exception

from .failures import WebFailureKind


WEB_RUNTIME_REASON_MAP = {
    WebFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
}

WEB_FAILURE_MESSAGES = {
    WebFailureKind.CONFIGURATION_FAILED: "Web configuration is invalid.",
}


@dataclass(frozen=True)
class RuntimeWebBridge:
    def from_config_error(self, error: ConfigError) -> RuntimeException:
        kind = WebFailureKind.CONFIGURATION_FAILED
        return runtime_exception(
            module="web",
            kind=kind,
            reason=WEB_RUNTIME_REASON_MAP[kind],
            message=WEB_FAILURE_MESSAGES[kind],
            payload=config_error_payload(error),
        )
