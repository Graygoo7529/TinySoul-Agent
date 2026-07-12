"""Agent Home-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.home.errors import (
    AgentHomeContractError,
    AgentHomeInvariantError,
    AgentHomeIOError,
)
from tinysoul.home.failures import AgentHomeFailureKind
from tinysoul.infra.config import ConfigError
from tinysoul.infra.json import JsonObject

from ..exception import (
    HOME_RUNTIME_COPY_REQUIRED,
    RUNTIME_STARTUP_FAILED,
    RUNTIME_TURN_END,
    RuntimeException,
)
from ._payload import config_error_payload, exception_payload, runtime_exception

HOME_RUNTIME_REASON_MAP: dict[AgentHomeFailureKind, str] = {
    AgentHomeFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    AgentHomeFailureKind.CONTRACT_VIOLATION: RUNTIME_TURN_END,
    AgentHomeFailureKind.IO_FAILED: RUNTIME_TURN_END,
    AgentHomeFailureKind.RUNTIME_COPY_REQUIRED: HOME_RUNTIME_COPY_REQUIRED,
    AgentHomeFailureKind.INTERNAL_FAILURE: RUNTIME_TURN_END,
}


@dataclass(frozen=True)
class RuntimeAgentHomeBridge:
    """Convert Agent Home boundary failures into runtime semantic exceptions."""

    def from_failure(
        self,
        kind: AgentHomeFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="home",
            kind=kind,
            reason_map=HOME_RUNTIME_REASON_MAP,
            message=message,
            payload=payload,
        )

    def from_exception(
        self,
        kind: AgentHomeFailureKind,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            kind,
            message=str(error),
            payload=exception_payload(error, payload),
        )

    def from_home_error(
        self,
        error: Exception,
        *,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        kind = AgentHomeFailureKind.INTERNAL_FAILURE
        if isinstance(error, AgentHomeContractError):
            kind = AgentHomeFailureKind.CONTRACT_VIOLATION
        elif isinstance(error, AgentHomeInvariantError):
            kind = AgentHomeFailureKind.INTERNAL_FAILURE
        elif isinstance(error, AgentHomeIOError):
            kind = AgentHomeFailureKind.IO_FAILED
        return self.from_exception(kind, error, payload=payload)

    def runtime_copy_required(
        self,
        *,
        link: str,
        message: str = "Agent Home runtime copy is required.",
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        runtime_payload: JsonObject = {"link": link}
        if payload is not None:
            runtime_payload = {**runtime_payload, **payload}
        return self.from_failure(
            AgentHomeFailureKind.RUNTIME_COPY_REQUIRED,
            message=message,
            payload=runtime_payload,
        )

    def startup_failure(
        self,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return self.from_failure(
            AgentHomeFailureKind.CONFIGURATION_FAILED,
            message=message,
            payload=payload,
        )

    def from_config_error(self, error: ConfigError) -> RuntimeException:
        return self.from_failure(
            AgentHomeFailureKind.CONFIGURATION_FAILED,
            message=error.message,
            payload=config_error_payload(error),
        )
