"""Local Endpoint settings."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
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
    event_page_bytes: int = 1024 * 1024
    journal_enabled: bool = True
    journal_root: Path | None = None
    journal_segment_bytes: int = 8 * 1024 * 1024
    journal_total_bytes: int = 256 * 1024 * 1024
    websocket_heartbeat_seconds: float = 15.0
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
        if (
            isinstance(self.websocket_heartbeat_seconds, bool)
            or not isinstance(self.websocket_heartbeat_seconds, (int, float))
            or self.websocket_heartbeat_seconds <= 0
        ):
            raise EndpointContractError(
                "Endpoint websocket heartbeat must be positive"
            )
        if not isinstance(self.journal_enabled, bool):
            raise EndpointContractError("Endpoint journal_enabled must be a bool")
        if self.journal_root is not None and not isinstance(self.journal_root, Path):
            raise EndpointContractError("Endpoint journal_root must be a Path")
        object.__setattr__(self, "instance_id", instance_id.strip())
        for name in (
            "event_capacity",
            "event_bytes",
            "event_page_bytes",
            "journal_segment_bytes",
            "journal_total_bytes",
            "max_request_bytes",
            "max_resource_chars",
            "max_resource_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise EndpointContractError(f"Endpoint {name} must be positive")
        if self.journal_segment_bytes > self.journal_total_bytes:
            raise EndpointContractError(
                "Endpoint journal_segment_bytes cannot exceed journal_total_bytes"
            )
