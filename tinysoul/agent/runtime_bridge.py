"""App-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.agent.errors import AgentContractError
from tinysoul.agent.failures import AgentFailureKind
from tinysoul.infra.config import ConfigError
from tinysoul.infra.config.errors import config_error_payload
from tinysoul.infra.json import JsonObject
from tinysoul.runtime.control.exception import (
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from tinysoul.runtime.failures import exception_payload, runtime_exception

APP_RUNTIME_REASON_MAP: dict[AgentFailureKind, str] = {
    AgentFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    AgentFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    AgentFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


APP_FAILURE_MESSAGES: dict[AgentFailureKind, str] = {
    AgentFailureKind.CONFIGURATION_FAILED: "App configuration is invalid.",
    AgentFailureKind.CONTRACT_VIOLATION: "App call violated its contract.",
    AgentFailureKind.INTERNAL_FAILURE: "App operation failed internally.",
}


@dataclass(frozen=True)
class RuntimeAgentBridge:
    """Convert app boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: AgentFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="agent",
            kind=kind,
            reason=APP_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=payload,
        )

    def from_exception(
        self,
        kind: AgentFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            kind,
            message=APP_FAILURE_MESSAGES[kind],
            payload=exception_payload(error, payload),
        )

    def from_agent_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = AgentFailureKind.INTERNAL_FAILURE
        if isinstance(error, AgentContractError):
            kind = AgentFailureKind.CONTRACT_VIOLATION
        return self.from_exception(kind, error, payload=payload)

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            AgentFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            AgentFailureKind.CONFIGURATION_FAILED,
            message=APP_FAILURE_MESSAGES[AgentFailureKind.CONFIGURATION_FAILED],
            payload=config_error_payload(error),
        )
