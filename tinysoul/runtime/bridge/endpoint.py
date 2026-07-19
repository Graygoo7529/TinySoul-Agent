"""Endpoint-to-runtime semantic bridge."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.endpoint.errors import (
    EndpointContractError,
    EndpointError,
    EndpointServerError,
)
from tinysoul.endpoint.failures import EndpointFailureKind
from tinysoul.infra.json import JsonObject

from ..exception import RUNTIME_STARTUP_FAILED, RuntimeException
from ._payload import exception_payload, runtime_exception


ENDPOINT_RUNTIME_REASON_MAP: dict[EndpointFailureKind, str] = {
    EndpointFailureKind.CONFIGURATION_FAILED: RUNTIME_STARTUP_FAILED,
    EndpointFailureKind.SERVER_FAILED: RUNTIME_STARTUP_FAILED,
    EndpointFailureKind.INTERNAL_FAILURE: RUNTIME_STARTUP_FAILED,
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
            reason_map=ENDPOINT_RUNTIME_REASON_MAP,
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
            message=str(error),
            payload=exception_payload(error),
        )
