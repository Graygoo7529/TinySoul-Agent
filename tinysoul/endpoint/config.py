"""Local Endpoint settings."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from uuid import uuid4

from .errors import EndpointContractError


@dataclass(frozen=True)
class EndpointSettings:
    """Validated local-only server and bounded event settings."""

    host: str = "127.0.0.1"
    port: int = 0
    token: str = ""
    instance_id: str = ""
    project_identity: str = ""
    event_capacity: int = 2000
    event_bytes: int = 32 * 1024 * 1024
    max_request_bytes: int = 8 * 1024 * 1024
    max_resource_chars: int = 2 * 1024 * 1024
    max_resource_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        try:
            address = ip_address(self.host)
        except ValueError as exc:
            raise EndpointContractError(
                "Endpoint host must be a loopback IP address"
            ) from exc
        if not address.is_loopback:
            raise EndpointContractError("Endpoint may only bind to loopback")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise EndpointContractError("Endpoint port must be an integer")
        if not 0 <= self.port <= 65535:
            raise EndpointContractError("Endpoint port must be between 0 and 65535")
        if not isinstance(self.token, str) or len(self.token) < 32:
            raise EndpointContractError(
                "Endpoint bearer token must contain at least 32 characters"
            )
        instance_id = self.instance_id or f"instance_{uuid4().hex}"
        if not isinstance(instance_id, str) or not instance_id.strip():
            raise EndpointContractError("Endpoint instance_id must be non-empty")
        if not isinstance(self.project_identity, str):
            raise EndpointContractError("Endpoint project_identity must be text")
        object.__setattr__(self, "instance_id", instance_id.strip())
        for name in (
            "event_capacity",
            "event_bytes",
            "max_request_bytes",
            "max_resource_chars",
            "max_resource_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise EndpointContractError(f"Endpoint {name} must be positive")
