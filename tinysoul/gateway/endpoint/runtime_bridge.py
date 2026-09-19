"""Endpoint-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.gateway.endpoint.errors import (
    EndpointContractError,
    EndpointError,
    EndpointServerError,
)
from tinysoul.gateway.endpoint.failures import EndpointFailureKind
from tinysoul.infra.json import JsonObject
from tinysoul.runtime.control.exception import RUNTIME_STARTUP_FAILED, RuntimeException
from tinysoul.runtime.failures import exception_payload, runtime_exception

ENDPOINT_RUNTIME_REASON_MAP: dict[EndpointFailureKind, str] = {
    EndpointFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    EndpointFailureKind.SERVER_FAILED: RUNTIME_STARTUP_FAILED,
    EndpointFailureKind.INTERNAL_FAILURE: RUNTIME_STARTUP_FAILED,
}


ENDPOINT_FAILURE_MESSAGES: dict[EndpointFailureKind, str] = {
    EndpointFailureKind.CONFIGURATION_FAILED: "Endpoint configuration is invalid.",
    EndpointFailureKind.SERVER_FAILED: "Endpoint service could not start.",
    EndpointFailureKind.INTERNAL_FAILURE: "Endpoint operation failed internally.",
}


@dataclass(frozen=True)
class RuntimeEndpointBridge:
    """Convert Endpoint service failures into Runtime startup semantics."""

    def from_failure(
        self,
        kind: EndpointFailureKind,
        *,
        message: str,
        payload: JsonObject | None = None,
    ) -> RuntimeException:
        return runtime_exception(
            module="endpoint",
            kind=kind,
            reason=ENDPOINT_RUNTIME_REASON_MAP[kind],
            message=message,
            payload=payload,
        )

    def from_endpoint_error(self, error: EndpointError) -> RuntimeException:
        kind = EndpointFailureKind.INTERNAL_FAILURE
        if isinstance(error, EndpointContractError):
            kind = EndpointFailureKind.CONFIGURATION_FAILED
        elif isinstance(error, EndpointServerError):
            kind = EndpointFailureKind.SERVER_FAILED
        return self.from_failure(
            kind,
            message=ENDPOINT_FAILURE_MESSAGES[kind],
            payload=exception_payload(error),
        )
